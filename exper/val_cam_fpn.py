import sys

sys.path.append('../')
import argparse
import os
from tqdm import tqdm
import numpy as np
import json

import torch
import torch.nn.functional as F

from utils import AverageMeter
from utils import evaluate
from utils.loader import data_loader
from utils.restore import restore
from utils.localization import get_topk_boxes, get_topk_boxes_hier
from utils.vistools import save_im_heatmap_box, save_im_gcam_ggrads
from models import *
import cv2
# default settings

LR = 0.001
EPOCH = 200
DISP_INTERVAL = 50

# default settings
ROOT_DIR = os.getcwd()
SNAPSHOT_DIR = os.path.join(ROOT_DIR, 'snapshots', 'snapshot_bins')
IMG_DIR = os.path.abspath(os.path.join(ROOT_DIR, '../data', 'CUB_200_2011/images'))
train_list = os.path.abspath(os.path.join(ROOT_DIR, '../data', 'CUB_200_2011/list/train.txt'))
train_root_list = os.path.abspath(os.path.join(ROOT_DIR, '../data','CUB_200_2011/list/order_label.txt'))
train_parent_list = os.path.abspath(os.path.join(ROOT_DIR, '../data','CUB_200_2011/list/family_label.txt'))

test_list = os.path.abspath(os.path.join(ROOT_DIR, '../data','CUB_200_2011/list/test.txt'))
testbox_list = os.path.abspath(os.path.join(ROOT_DIR, '../data','CUB_200_2011/list/test_boxes.txt'))
class opts(object):
    def __init__(self):
        self.parser = argparse.ArgumentParser(description='ECCV')
        self.parser.add_argument("--root_dir", type=str, default='')
        self.parser.add_argument("--img_dir", type=str, default=IMG_DIR)
        self.parser.add_argument("--train_list", type=str, default=train_list)
        self.parser.add_argument("--train_root_list", type=str, default=train_root_list)
        self.parser.add_argument("--train_parent_list", type=str, default=train_parent_list)
        self.parser.add_argument("--test_list", type=str, default=test_list)
        self.parser.add_argument("--test_box", type=str, default=testbox_list)
        self.parser.add_argument("--batch_size", type=int, default=1)
        self.parser.add_argument("--input_size", type=int, default=256)
        self.parser.add_argument("--crop_size", type=int, default=224)
        self.parser.add_argument("--dataset", type=str, default='imagenet')
        self.parser.add_argument("--num_classes", type=int, default=200)
        self.parser.add_argument("--arch", type=str, default='vgg_v0')
        self.parser.add_argument("--threshold", type=str, default='0.1,0.15,0.2,0.25,0.3,0.35,0.4,0.45')
        self.parser.add_argument("--lr", type=float, default=LR)
        self.parser.add_argument("--decay_points", type=str, default='none')
        self.parser.add_argument("--epoch", type=int, default=EPOCH)
        self.parser.add_argument("--tencrop", type=str, default='True')
        self.parser.add_argument("--onehot", type=str, default='False')
        self.parser.add_argument("--gpus", type=str, default='0', help='-1 for cpu, split gpu id by comma')
        self.parser.add_argument("--num_workers", type=int, default=12)
        self.parser.add_argument("--disp_interval", type=int, default=DISP_INTERVAL)
        self.parser.add_argument("--snapshot_dir", type=str, default='')
        self.parser.add_argument("--resume", type=str, default='True')
        self.parser.add_argument("--restore_from", type=str, default='')
        self.parser.add_argument("--global_counter", type=int, default=0)
        self.parser.add_argument("--current_epoch", type=int, default=0)
        self.parser.add_argument("--debug", action='store_true', help='.')
        self.parser.add_argument("--vis_feat", action='store_true', help='.')
        self.parser.add_argument("--vis_var", action='store_true', help='.')
        self.parser.add_argument("--debug_dir", type=str, default='../debug', help='save visualization results.')
        self.parser.add_argument("--vis_dir", type=str, default='../vis_dir', help='save visualization results.')
        self.parser.add_argument("--mce", action='store_true',
                                 help='classification loss using cross entropy.')
        self.parser.add_argument("--bg", action='store_true',help='grad_cam for background.')
        self.parser.add_argument("--IN", action='store_true', help='switch off instance norm layer in first two conv blocks in Network.')
        self.parser.add_argument("--INL", action='store_true', help='switch off instance norm layer with learn affine parms in first two conv blocks in Network.')
        self.parser.add_argument("--loss_trunc_th", type=float, default=1.0, help='The samples whose prediction score are higher than loss_trunc_th are detached.')
        self.parser.add_argument("--trunc_loss", action='store_true', help='switch on truncation loss.')
        self.parser.add_argument("--RGAP", action='store_true', help='switch on residualized gap block.')
        self.parser.add_argument("--sc", action='store_true', help='switch on the class similar loss.')
        self.parser.add_argument("--bin_cls", action='store_true', help='switch on the binary classification.')
        self.parser.add_argument("--carafe", action='store_true', help='switch on the carafe.')
        self.parser.add_argument("--carafe_cls", action='store_true', help='switch on the carafe.')
        self.parser.add_argument("--non_local", action='store_true', help='switch on the non-local.')
        self.parser.add_argument("--nl_blocks", type=str, default='3,4,5', help='3 for feat3, etc.')
        self.parser.add_argument("--nl_residual", action='store_true',
                                 help='switch on the non-local with residual path.')
        self.parser.add_argument("--nl_kernel", type=int, default=-1, help='the kernel for non local module.')
        self.parser.add_argument("--nl_pairfunc", type=int, default=0,
                                 help='0 for guassian embedding, 1 for dot production')
        self.parser.add_argument("--sep_loss", action='store_true', help='switch on calculating loss for each individual.')
        self.parser.add_argument("--loc_branch", action='store_true', help='switch on location branch.')
        self.parser.add_argument("--com_feat", action='store_true', help='switch on location branch.')

        self.parser.add_argument("--loss_w_3", type=float, default=1., help='weight of classification loss for 3-th level.')
        self.parser.add_argument("--loss_w_4", type=float, default=1., help='weight of classification loss for 4-th level.')
        self.parser.add_argument("--loss_w_5", type=float, default=1., help='weight of classification loss for 5-th level.')
        self.parser.add_argument("--loss_w_6", type=float, default=1., help='weight of classification loss for 6-th level.')
        self.parser.add_argument("--vis_th", type=float, default=0.9, help='threshold for visualizatoin')
        self.parser.add_argument("--fpn", action='store_true', help='switch on adopting fpn architecture.')
        self.parser.add_argument("--bifpn", action='store_true', help='switch on adopting bifpn architecture.')

    def parse(self):
        opt = self.parser.parse_args()
        opt.gpus_str=opt.gpus
        opt.gpus = list(map(int, opt.gpus.split(',')))
        opt.gpus = [i for i in range(len(opt.gpus))] if opt.gpus[0]>=0 else [-1]
        opt.threshold = list(map(float, opt.threshold.split(',')))
        if 'vgg' in opt.arch:
            opt.size=(28, 28)
        else:
            opt.size=(25, 25)
        return opt

def get_model(args):
    model = eval(args.arch).model(num_classes=args.num_classes, args=args)

    model = torch.nn.DataParallel(model, args.gpus)
    model.cuda()

    if args.resume == 'True':
        restore(args, model, None, istrain=False)

    return model


def eval_loc(cls_logits, cls_map, img_path, input_size, crop_size, label, gt_boxes,
             topk=(1,5), threshold=None, mode='union', debug=False, debug_dir=None, gcam=False,
             g2=False, NoHDA=True, com_feat=False, bin_map=False):
    top_boxes, top_maps = get_topk_boxes_hier(cls_logits[0], None, None, cls_map, None, None, img_path, input_size,
                                              crop_size, topk=topk, threshold=threshold, mode=mode, gcam=gcam, g2=g2,
                                              NoHDA=NoHDA, com_feat=com_feat, bin_map=bin_map)
    top1_box, top5_boxes = top_boxes

    # update result record
    deterr_1,locerr_1, deterr_5, locerr_5 = evaluate.locerr((top1_box, top5_boxes), label.data.long().numpy(), gt_boxes,
                                         topk=(1, 5))

    # if debug and threshold==0.15:
    #     save_im_heatmap_box(img_path, top_maps, top5_boxes, debug_dir,
    #                         gt_label=label.data.long().numpy(),
    #                         gt_box=gt_boxes, threshold=threshold, gcam=gcam, g2=g2)

    return deterr_1, locerr_1, deterr_5, locerr_5, top_maps, top5_boxes

def vis_feature(feat, img_path, vis_path, col=4, row=4, layer='feat3'):
    ## normalize feature
    feat = feat[0,...]
    c, fh, fw = feat.size()
    feat = feat.view(c, -1)
    min_val, _ = torch.min(feat, dim=-1, keepdim=True)
    max_val, _ = torch.max(feat, dim=-1, keepdim=True)
    norm_feat = (feat - min_val) / (max_val - min_val+1e-10)
    norm_feat = norm_feat.view(c, fh, fw).contiguous().permute(1,2,0)
    norm_feat = norm_feat.data.cpu().numpy()

    im = cv2.imread(img_path)
    h, w, _ = np.shape(im)
    resized_feat = cv2.resize(norm_feat, (w, h))

    # draw images
    feat_ind = 0
    fig_id = 0

    while feat_ind < c:
        im_to_save = []
        for i in range(row):
            draw_im = 255 * np.ones((h + 15, w+5, 3), np.uint8)
            draw_im[:h, :w, :] = im
            cv2.putText(draw_im, 'original image', (0, h + 12), color=(0, 0, 0),
                        fontFace=cv2.FONT_HERSHEY_COMPLEX,
                        fontScale=0.5)
            im_to_save_row = [draw_im.copy()]
            for j in range(col):
                draw_im = 255 * np.ones((h + 15, w + 5, 3), np.uint8)
                draw_im[:h, :w, :] = im

                heatmap = cv2.applyColorMap(np.uint8(255 * resized_feat[:,:,feat_ind]), cv2.COLORMAP_JET)
                draw_im[:h, :w, :] = heatmap * 0.7 + draw_im[:h, :w, :] * 0.3

                im_to_save_row.append(draw_im.copy())
                feat_ind += 1
            im_to_save_row = np.concatenate(im_to_save_row, axis=1)
            im_to_save.append(im_to_save_row)
        im_to_save = np.concatenate(im_to_save, axis=0)
        vis_path = os.path.join(vis_path,'vis_feat')
        if not os.path.exists(vis_path):
            os.makedirs(vis_path)
        save_name = 'vgg_' + img_path.split('/')[-1]
        save_name = save_name.replace('.','_{}_{}.'.format(layer, fig_id))
        cv2.imwrite(os.path.join(vis_path, save_name), im_to_save)
        fig_id +=1

def vis_var(feat, cls_logits, img_path, vis_path, net='vgg_baseline'):

    cls_logits = cls_logits.squeeze()

    norm_var_no_white = norm_tensor(feat)
    norm_cls_no_white = norm_tensor(cls_logits)

    white_feat = whitening_tensor(feat)
    white_cls_logits = whitening_tensor(cls_logits)
    norm_var = norm_tensor(white_feat)
    norm_cls = norm_tensor(white_cls_logits)

    im = cv2.imread(img_path)
    h, w, _ = np.shape(im)
    resized_var_no_white = cv2.resize(norm_var_no_white, (w, h)) <0.7
    resized_cls_no_white = cv2.resize(norm_cls_no_white, (w, h)) >0.2
    resized_var = cv2.resize(norm_var, (w, h)) <0.2
    resized_cls= cv2.resize(norm_cls, (w, h)) >0.5

    draw_im = 255 * np.ones((h + 15, w+5, 3), np.uint8)
    draw_im[:h, :w, :] = im
    cv2.putText(draw_im, 'original image', (0, h + 12), color=(0, 0, 0),
                fontFace=cv2.FONT_HERSHEY_COMPLEX,
                fontScale=0.5)
    im_to_save = [draw_im.copy()]

    draw_im = 255 * np.ones((h + 15, w + 5, 3), np.uint8)
    draw_im[:h, :w, :] = im
    heatmap = cv2.applyColorMap(np.uint8(255 * resized_var_no_white), cv2.COLORMAP_JET)
    draw_im[:h, :w, :] = heatmap * 0.5 + draw_im[:h, :w, :] * 0.5
    cv2.putText(draw_im, 'var_nw', (0, h + 12), color=(0, 0, 0),
                fontFace=cv2.FONT_HERSHEY_COMPLEX,
                fontScale=0.5)
    im_to_save.append(draw_im.copy())

    draw_im = 255 * np.ones((h + 15, w + 5, 3), np.uint8)
    draw_im[:h, :w, :] = im
    heatmap = cv2.applyColorMap(np.uint8(255 * resized_cls_no_white), cv2.COLORMAP_JET)
    draw_im[:h, :w, :] = heatmap * 0.5 + draw_im[:h, :w, :] * 0.5
    cv2.putText(draw_im, 'cls_nw', (0, h + 12), color=(0, 0, 0),
                fontFace=cv2.FONT_HERSHEY_COMPLEX,
                fontScale=0.5)
    im_to_save.append(draw_im.copy())

    draw_im = 255 * np.ones((h + 15, w + 5, 3), np.uint8)
    draw_im[:h, :w, :] = im
    resized_var_cls_no_white = (resized_var_no_white + resized_cls_no_white)*0.5
    heatmap = cv2.applyColorMap(np.uint8(255 * resized_var_cls_no_white), cv2.COLORMAP_JET)
    draw_im[:h, :w, :] = heatmap * 0.5 + draw_im[:h, :w, :] * 0.5
    cv2.putText(draw_im, 'var_cls_nw', (0, h + 12), color=(0, 0, 0),
                fontFace=cv2.FONT_HERSHEY_COMPLEX,
                fontScale=0.5)
    im_to_save.append(draw_im.copy())


    draw_im = 255 * np.ones((h + 15, w + 5, 3), np.uint8)
    draw_im[:h, :w, :] = im
    heatmap = cv2.applyColorMap(np.uint8(255 * resized_var), cv2.COLORMAP_JET)
    draw_im[:h, :w, :] = heatmap * 0.5 + draw_im[:h, :w, :] * 0.5
    cv2.putText(draw_im, 'var', (0, h + 12), color=(0, 0, 0),
                fontFace=cv2.FONT_HERSHEY_COMPLEX,
                fontScale=0.5)
    im_to_save.append(draw_im.copy())

    draw_im = 255 * np.ones((h + 15, w + 5, 3), np.uint8)
    draw_im[:h, :w, :] = im
    heatmap = cv2.applyColorMap(np.uint8(255 * resized_cls), cv2.COLORMAP_JET)
    draw_im[:h, :w, :] = heatmap * 0.5 + draw_im[:h, :w, :] * 0.5
    cv2.putText(draw_im, 'cls', (0, h + 12), color=(0, 0, 0),
                fontFace=cv2.FONT_HERSHEY_COMPLEX,
                fontScale=0.5)
    im_to_save.append(draw_im.copy())

    draw_im = 255 * np.ones((h + 15, w + 5, 3), np.uint8)
    draw_im[:h, :w, :] = im
    resized_var_cls = (resized_var + resized_cls) * 0.5
    heatmap = cv2.applyColorMap(np.uint8(255 * resized_var_cls), cv2.COLORMAP_JET)
    draw_im[:h, :w, :] = heatmap * 0.5 + draw_im[:h, :w, :] * 0.5
    cv2.putText(draw_im, 'var_cls', (0, h + 12), color=(0, 0, 0),
                fontFace=cv2.FONT_HERSHEY_COMPLEX,
                fontScale=0.5)
    im_to_save.append(draw_im.copy())

    im_to_save = np.concatenate(im_to_save, axis=1)

    vis_path = os.path.join(vis_path, 'vis_var/{}'.format(net))
    if not os.path.exists(vis_path):
        os.makedirs(vis_path)
    save_name = 'vgg_' + img_path.split('/')[-1]
    cv2.imwrite(os.path.join(vis_path, save_name), im_to_save)

def norm_tensor(feat):
    min_val = torch.min(feat)
    max_val = torch.max(feat)
    norm_feat = (feat - min_val) / (max_val - min_val + 1e-20)
    norm_feat = norm_feat.data.cpu().numpy()
    return norm_feat

def whitening_tensor(feat):
    mean = torch.mean(feat)
    var = torch.std(feat)
    norm_feat = (feat-mean)/(var+1e-15)
    return norm_feat

def norm_atten_map(attention_map):
    min_val = np.min(attention_map)
    max_val = np.max(attention_map)
    atten_norm = (attention_map - min_val) / (max_val - min_val+1e-10)
    return atten_norm

def val(args):
    os.environ['CUDA_VISIBLE_DEVICES'] = args.gpus_str

    print('Running parameters:\n')
    print(json.dumps(vars(args), indent=4, separators=(',', ':')))

    if not os.path.exists(args.snapshot_dir):
        os.mkdir(args.snapshot_dir)

    with open(args.test_box, 'r') as f:
        gt_boxes = [list(map(float, x.strip().split(' ')[2:])) for x in f.readlines()]
    gt_boxes = [(box[0], box[1], box[0]+box[2]-1, box[1]+box[3]-1) for box in gt_boxes]

    # meters

    top1_f5_clsacc = AverageMeter()
    top5_f5_clsacc = AverageMeter()
    top1_f6_clsacc = AverageMeter()
    top5_f6_clsacc = AverageMeter()
    top1_f5_clsacc.reset()
    top5_f5_clsacc.reset()
    top1_f6_clsacc.reset()
    top5_f6_clsacc.reset()

    loc_err = {}

    for th in args.threshold:
        loc_err['top1_f3_locerr_{}'.format(th)] = AverageMeter()
        loc_err['top1_f3_locerr_{}'.format(th)].reset()
        loc_err['top5_f3_locerr_{}'.format(th)] = AverageMeter()
        loc_err['top5_f3_locerr_{}'.format(th)].reset()
        loc_err['top1_f3_deterr_{}'.format(th)] = AverageMeter()
        loc_err['top1_f3_deterr_{}'.format(th)].reset()
        loc_err['top5_f3_deterr_{}'.format(th)] = AverageMeter()
        loc_err['top5_f3_deterr_{}'.format(th)].reset()
        loc_err['top1_f4_locerr_{}'.format(th)] = AverageMeter()
        loc_err['top1_f4_locerr_{}'.format(th)].reset()
        loc_err['top5_f4_locerr_{}'.format(th)] = AverageMeter()
        loc_err['top5_f4_locerr_{}'.format(th)].reset()
        loc_err['top1_f4_deterr_{}'.format(th)] = AverageMeter()
        loc_err['top1_f4_deterr_{}'.format(th)].reset()
        loc_err['top5_f4_deterr_{}'.format(th)] = AverageMeter()
        loc_err['top5_f4_deterr_{}'.format(th)].reset()

    # get model
    model = get_model(args)
    model.eval()

    # get data
    _, valcls_loader, valloc_loader = data_loader(args, test_path=True)
    assert len(valcls_loader) == len(valloc_loader), \
        'Error! Different size for two dataset: loc({}), cls({})'.format(len(valloc_loader), len(valcls_loader))

    # testing
    if args.debug:
        # show_idxs = np.arange(20)
        np.random.seed(2333)
        show_idxs = np.arange(len(valcls_loader))
        np.random.shuffle(show_idxs)
        show_idxs = show_idxs[:100]

    # evaluation classification task

    for idx, (dat_cls, dat_loc ) in tqdm(enumerate(zip(valcls_loader, valloc_loader))):
        grads = {}
        # parse data
        img_path, img, label_in = dat_cls
        if args.tencrop == 'True':
            bs, ncrops, c, h, w = img.size()
            img = img.view(-1, c, h, w)

        # forward pass
        args.device = torch.device('cuda') if args.gpus[0]>=0 else torch.device('cpu')
        img = img.to(args.device)
        # img_var, label_var = Variable(img), Variable(label)
        if args.vis_feat:
            if idx in show_idxs:
                _, img_loc, label = dat_loc
                _ = model(img_loc)
                vis_feature(model.module.feat3, img_path[0], args.vis_dir, layer='feat3')
                vis_feature(model.module.feat4, img_path[0], args.vis_dir, layer='feat4')
                vis_feature(model.module.feat5, img_path[0], args.vis_dir, layer='feat5')
            continue
        if args.vis_var:
            if idx in show_idxs:
                _, img_loc, label = dat_loc
                logits = model(img_loc)
                cls_logits = F.softmax(logits[2],dim=1)
                var_logits = torch.var(cls_logits,dim=1).squeeze()
                vis_var(var_logits, cls_logits[0,label.long(),...], img_path[0], args.vis_dir, net='vis_var_vgg_16_fpn_l5_1_100e_7_2')
            continue
        logits = model(img)

        logits3, logits4, logits5, logits6 = logits
        cls_logits_5 = torch.mean(torch.mean(logits5, dim=2), dim=2)
        cls_logits_6 = torch.mean(torch.mean(logits6, dim=2), dim=2)

        cls_logits_5 = F.softmax(cls_logits_5, dim=1)
        cls_logits_6 = F.softmax(cls_logits_6, dim=1)
        if args.tencrop == 'True':
            cls_logits_5 = cls_logits_5.view(1, ncrops, -1).mean(1)
            cls_logits_6 = cls_logits_6.view(1, ncrops, -1).mean(1)

        prec1_f5, prec5_f5 = evaluate.accuracy(cls_logits_5.cpu().data, label_in.long(), topk=(1, 5))
        top1_f5_clsacc.update(prec1_f5[0].numpy(), img.size()[0])
        top5_f5_clsacc.update(prec5_f5[0].numpy(), img.size()[0])

        prec1_f6, prec5_f6 = evaluate.accuracy(cls_logits_6.cpu().data, label_in.long(), topk=(1, 5))
        top1_f6_clsacc.update(prec1_f6[0].numpy(), img.size()[0])
        top5_f6_clsacc.update(prec5_f6[0].numpy(), img.size()[0])

        _, img_loc, label = dat_loc
        cls_map_3, cls_map_4, cls_map_5, cls_map_6= model(img_loc)

        if args.loc_branch:
            pass
            # loc_map = loc_map[:,:-1,...] - loc_map[:,-1:,...]
            # bg_map = loc_map[0,-1,...].data.cpu().numpy()
            # bg_map = norm_atten_map(bg_map)

        if args.loss_w_3 >0.:
            cls_map_3 = torch.sigmoid(cls_map_3)
            for th in args.threshold:
                deterr_1, locerr_1, deterr_5, locerr_5, top_maps, top5_boxes = eval_loc(cls_logits_5, cls_map_3,
                                                img_path[0], args.input_size, args.crop_size, label, gt_boxes[idx],
                                                topk=(1, 5), threshold=th, mode='union', debug=args.debug,
                                                debug_dir=args.debug_dir, NoHDA=True, bin_map = args.loc_branch)
                loc_err['top1_f3_deterr_{}'.format(th)].update(deterr_1, img.size()[0])
                loc_err['top5_f3_deterr_{}'.format(th)].update(deterr_5, img.size()[0])
                loc_err['top1_f3_locerr_{}'.format(th)].update(locerr_1, img.size()[0])
                loc_err['top5_f3_locerr_{}'.format(th)].update(locerr_5, img.size()[0])
                if args.debug and idx in show_idxs and th == args.vis_th:
                    save_im_heatmap_box(img_path[0], top_maps, top5_boxes, args.debug_dir,
                                        gt_label=label.data.long().numpy(), sim_map=None, bg_map=None,
                                        gt_box=gt_boxes[idx], epoch=args.current_epoch,threshold=th, suffix='lv3')
        if args.loss_w_4 >0.:
            cls_map_4 = torch.sigmoid(cls_map_4)
            for th in args.threshold:
                deterr_1, locerr_1, deterr_5, locerr_5, top_maps, top5_boxes = eval_loc(cls_logits_5, cls_map_4,
                                                img_path[0], args.input_size, args.crop_size, label, gt_boxes[idx],
                                                topk=(1, 5), threshold=th, mode='union', debug=args.debug,
                                                debug_dir=args.debug_dir, NoHDA=True, bin_map = args.loc_branch)
                loc_err['top1_f4_deterr_{}'.format(th)].update(deterr_1, img.size()[0])
                loc_err['top5_f4_deterr_{}'.format(th)].update(deterr_5, img.size()[0])
                loc_err['top1_f4_locerr_{}'.format(th)].update(locerr_1, img.size()[0])
                loc_err['top5_f4_locerr_{}'.format(th)].update(locerr_5, img.size()[0])
                if args.debug and idx in show_idxs and th == args.vis_th:
                    save_im_heatmap_box(img_path[0], top_maps, top5_boxes, args.debug_dir,
                                        gt_label=label.data.long().numpy(), sim_map=None, bg_map=None,
                                        gt_box=gt_boxes[idx], epoch=args.current_epoch,threshold=th, suffix='lv4')


    print('== cls err')

    if args.loss_w_5 > 0:
        print('Top1_f5: {:.2f} Top5_f5: {:.2f}\n'.format(100.0 - top1_f5_clsacc.avg, 100.0 - top5_f5_clsacc.avg))
    if args.loss_w_6 > 0:
        print('Top1_f6: {:.2f} Top5_f6: {:.2f}\n'.format(100.0 - top1_f6_clsacc.avg, 100.0 - top5_f6_clsacc.avg))


    for th in args.threshold:
        print('=========== threshold: {} ==========='.format(th))
        if args.loss_w_3 > 0:
            print('== det err')
            print('Top1_f3: {:.2f} Top5_f3: {:.2f}\n'.format(loc_err['top1_f3_deterr_{}'.format(th)].avg,
                                                                loc_err['top5_f3_deterr_{}'.format(th)].avg))
            print('== loc err ')
            print('Top1_f3: {:.2f} Top5_f3: {:.2f}\n'.format(loc_err['top1_f3_locerr_{}'.format(th)].avg,
                                                                loc_err['top5_f3_locerr_{}'.format(th)].avg))
        if args.loss_w_4 > 0:
            print('== det err')
            print('Top1_f4: {:.2f} Top5_f4: {:.2f}\n'.format(loc_err['top1_f4_deterr_{}'.format(th)].avg,
                                                                loc_err['top5_f4_deterr_{}'.format(th)].avg))
            print('== loc err ')
            print('Top1_f4: {:.2f} Top5_f4: {:.2f}\n'.format(loc_err['top1_f4_locerr_{}'.format(th)].avg,
                                                                loc_err['top5_f4_locerr_{}'.format(th)].avg))

    result_log = os.path.join(args.snapshot_dir, 'results.log')

    with open(result_log,'a') as fw:
        fw.write('current_epoch:{}\n'.format(args.current_epoch))
        fw.write('== cls err ')
        if args.loss_w_5 > 0:
            fw.write('Top1_f5: {:.2f} Top5_f5: {:.2f}\n'.format(100.0 - top1_f5_clsacc.avg, 100.0 - top5_f5_clsacc.avg))
        if args.loss_w_6 > 0:
            fw.write('Top1_f6: {:.2f} Top5_f6: {:.2f}\n'.format(100.0 - top1_f6_clsacc.avg, 100.0 - top5_f6_clsacc.avg))

        for th in args.threshold:
            fw.write('=========== threshold: {} ===========\n'.format(th))
            if args.loss_w_3 >0:
                fw.write('== det err')
                fw.write('Top1_f3: {:.2f} Top5_f3: {:.2f}\n'.format(loc_err['top1_f3_deterr_{}'.format(th)].avg,
                                                                 loc_err['top5_f3_deterr_{}'.format(th)].avg))
                fw.write('== loc err ')
                fw.write('Top1_f3: {:.2f} Top5_f3: {:.2f}\n'.format(loc_err['top1_f3_locerr_{}'.format(th)].avg,
                                                           loc_err['top5_f3_locerr_{}'.format(th)].avg))
            if args.loss_w_4 >0:
                fw.write('== det err')
                fw.write('Top1_f4: {:.2f} Top5_f4: {:.2f}\n'.format(loc_err['top1_f4_deterr_{}'.format(th)].avg,
                                                                 loc_err['top5_f4_deterr_{}'.format(th)].avg))
                fw.write('== loc err ')
                fw.write('Top1_f4: {:.2f} Top5_f4: {:.2f}\n'.format(loc_err['top1_f4_locerr_{}'.format(th)].avg,
                                                           loc_err['top5_f4_locerr_{}'.format(th)].avg))

if __name__ == '__main__':
    args = opts().parse()
    val(args)
