import sys
sys.path.extend([ '../', '../../'])
import torch
import dataloader as dl
from args import Args
from model import Het_ConEn, Het_NetEn, EdgePredictor, Het_classify
from train2 import train_smote

# Set device to GPU if available, else use CPU
args = Args()
args.imdb()
torch.cuda.empty_cache()

data = torch.load('../data/data.pt')
file_path = 'output/output2/up_ratio.txt'

device = args.device

# Send all x tensors to the device
data['m_text_embed']['x'] = data['m_text_embed']['x'].to(device)
data['m_net_embed']['x'] = data['m_net_embed']['x'].to(device)
data['m_a_net_embed']['x'] = data['m_a_net_embed']['x'].to(device)
data['m_d_net_embed']['x'] = data['m_d_net_embed']['x'].to(device)
data['a_net_embed']['x'] = data['a_net_embed']['x'].to(device)
data['a_text_embed']['x'] = data['a_text_embed']['x'].to(device)
data['d_net_embed']['x'] = data['d_net_embed']['x'].to(device)
data['d_text_embed']['x'] = data['d_text_embed']['x'].to(device)

# Send all y tensors to the device
data['m']['y'] = data['m']['y'].to(device)

# Send all edge_index tensors to the device
data['m', 'walk', 'm']['edge_index'] = data['m', 'walk', 'm']['edge_index'].to(device)
data['m', 'walk', 'a']['edge_index'] = data['m', 'walk', 'a']['edge_index'].to(device)
data['m', 'walk', 'd']['edge_index'] = data['m', 'walk', 'd']['edge_index'].to(device)
data['a', 'walk', 'm']['edge_index'] = data['a', 'walk', 'm']['edge_index'].to(device)
data['a', 'walk', 'a']['edge_index'] = data['a', 'walk', 'a']['edge_index'].to(device)
data['a', 'walk', 'd']['edge_index'] = data['a', 'walk', 'd']['edge_index'].to(device)
data['d', 'walk', 'm']['edge_index'] = data['d', 'walk', 'm']['edge_index'].to(device)
data['d', 'walk', 'a']['edge_index'] = data['d', 'walk', 'a']['edge_index'].to(device)
data['d', 'walk', 'd']['edge_index'] = data['d', 'walk', 'd']['edge_index'].to(device)

edge_indices = [ data['m', 'walk', 'm'].edge_index, data['m', 'walk', 'a'].edge_index, data['m', 'walk', 'd'].edge_index ]


train_dict = {
    0: 'no',
    1: 'up',
    2: 'smote',
    3: 'reweight',
    4: 'embed_sm',
    5: 'em_smote',
    6: 'pret',
    7: 'preo',
    8: 'preT', 
    9: 'preO',
    10: 'noFT',
    11: 'preT',
    12: 'preO'
} # 8, 9: pre enc + pre dec; 11,12: only pre dec

up_ratios = [1.2, 1.4, 1.6, 1.8, 2.0, 2.2]

with open(file_path, "w") as file:   #, open(file_path2, "w") as file2:
    
    for num, up in enumerate(up_ratios):
        
        args.portion = up
        train_data_idx, val_data_idx, test_data_idx = [], [], []
        
        file.write(f'\nUp_ratio: {up}\n')
            
        for p in range(10):
            c_train_num = dl.train_num(data['m'].y, args.im_class_num, args.class_samp_num[0], args.im_ratio)
            print(c_train_num, sum(c_train_num))
            train_idx, val_idx, test_idx, c_num_mat = dl.segregate(data['m'].y, c_train_num, args.seed[p], args)
            
            train_data_idx.append(train_idx)
            val_data_idx.append(val_idx)
            test_data_idx.append(test_idx)
            
        for k in range(0, 13):   
        
            if k < 6:
                train_mode = ''
                os_mode = train_dict[k]
            else:
                train_mode = train_dict[k]
                os_mode = 'gsm'
            
            if k > 10: file.write(f'\nOs_mode: {os_mode}, train_mode: {train_mode}2\n')  
            else: file.write(f'\nOs_mode: {os_mode}, train_mode: {train_mode}\n')     
            file.flush()
            Test_acc, Test_auc, Test_f1, auc_list, f1_list = [], [], [], [], []
    
            for p in range(10):
                    
                classifier = Het_classify(args.embed_dim, args.nclass, args.dropout)

                if k == 9 or k == 8:
                    encoder1 = torch.load('pretrained/encoder1.pth')
                    encoder2 = torch.load('pretrained/encoder2.pth')
                else:
                    encoder1 = Het_ConEn(args.embed_dim, args.dropout)
                    encoder2 = Het_NetEn(args.embed_dim, args.dropout)
                    
                if train_dict[k] == 'preT' or train_dict[k] == 'preO' or train_dict[k] == 'noFT':
                    decoder_m = torch.load('pretrained/decoder_m.pth')
                    decoder_a = torch.load('pretrained/decoder_a.pth')
                    decoder_d = torch.load('pretrained/decoder_d.pth')
                else: 
                    decoder_m = EdgePredictor(args.embed_dim)
                    decoder_a = EdgePredictor(args.embed_dim)
                    decoder_d = EdgePredictor(args.embed_dim)
            
                decoder_list = [decoder_m, decoder_a, decoder_d]
                #print(features.shape)
                encoder1.to(device)
                encoder2.to(device)
                classifier.to(device)
                for decoder in decoder_list:
                    decoder.to(device)
                    
                train_idx, val_idx, test_idx = train_data_idx[p], val_data_idx[p], test_data_idx[p]
            
                test_acc_list, test_auc_list, test_f1_list, auc_cls_list, f1_cls_list = train_smote(data, edge_indices, encoder1, 
                encoder2, classifier, decoder_list, train_idx, val_idx, test_idx, args, os_mode = os_mode, train_mode = train_mode)
                Test_acc.append(test_acc_list)
                Test_auc.append(test_auc_list)
                Test_f1.append(test_f1_list)
                auc_list.append(auc_cls_list)
                f1_list.append(f1_cls_list)
                torch.cuda.empty_cache()
        
            file.write(f'\nTest_acc:\n')
            for row in Test_acc:
                row_str = " ".join(map(str, row))
                file.write(row_str + "\n")
            file.write(f'\nTest_auc:\n')    
            for row in Test_auc:
                row_str = " ".join(map(str, row))
                file.write(row_str + "\n")
            file.write(f'\nTest_f1:\n')  
            for row in Test_f1:
                row_str = " ".join(map(str, row))
                file.write(row_str + "\n")
            file.flush()
            
            file.write(f'\nClass AUC Score:\n')  
            for row in auc_list:
                row_str = " ".join(map(str, row))
                file.write(row_str + "\n")
            file.write(f'\nClass F1 Score:\n')  
            for row in f1_list:  
                row_str = " ".join(map(str, row))
                file.write(row_str + "\n")
    
        
            