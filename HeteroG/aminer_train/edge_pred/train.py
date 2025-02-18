import torch
import torch.optim as optim
import torch.nn as nn
import torch.nn.functional as F
import time
from smote import oversample
from metric import edge_loss, accuracy, evaluate_class_performance
from sklearn import linear_model

w1 = 4
w2 = 2
w3 = 2

# Train Function on the entire data
def train_smote(data, edge_indices, target_edge, encoder, classifier, decoder_list, train_idx, val_idx, test_idx, args, os_mode, train_mode):
    
    epochs = list(range(0, 400, 20))
    edge_em = None

    val_acc_list, val_auc_list, val_f1_list = [], [], []
    test_acc_list, test_auc_list, test_f1_list = [], [], []
    loss_de, edge_ac = [], []
    auc_list, f1_list = [], []

    # Define your optimizer for encoder and classifier
    optimizer_en = optim.Adam(encoder.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    optimizer_cls = optim.Adam(classifier.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    optimizer_de = []

    encoder.train()
    classifier.train()
    
    for i in range(len(decoder_list)):
        optimizer_de.append(optim.Adam(decoder_list[i].parameters(), lr=args.lr, weight_decay=args.weight_decay))
        decoder_list[i].train()
    
    for epoch in range(args.num_epochs):

        optimizer_en.zero_grad()
        optimizer_cls.zero_grad()
        for optimizer in optimizer_de:
            optimizer.zero_grad()
        
        x_list = encoder(data, os_mode)
        
        if os_mode == 'gsm':
            x_list[1], new_labels , new_train_idx, ar_edge_indices, new_target_edge = oversample(features = x_list[1], labels = data['e'].y, 
            target_edge = target_edge, train_idx = train_idx, edge_indices = edge_indices, args= args, os_mode = 'gsm')
            
            edge_ac, loss_de, new_edge_indices = het_decode(decoder_list, x_list, edge_indices, ar_edge_indices, args, train_mode, dataset = 'Train')
            loss_de = [loss_de[0]*w1, loss_de[1]*w2, loss_de[2]*w3]
            del ar_edge_indices
                
        elif os_mode == 'embed_sm':
            x_list[1], new_labels , new_train_idx, new_target_edge = oversample(features = x_list[1], labels = data['e'].y, 
            target_edge = target_edge, train_idx = train_idx, edge_indices = None, args= args, os_mode = 'gsm')
            new_edge_indices = edge_indices
        elif os_mode == 'up':
            x_list[1], new_labels , new_train_idx, new_edge_indices, new_target_edge = oversample(features = x_list[1], labels = data['e'].y,  
            target_edge = target_edge, train_idx = train_idx, edge_indices = edge_indices, args= args, os_mode = 'up')
        elif os_mode == 'smote':
            x_list[1], new_labels , new_train_idx, new_edge_indices, new_target_edge  = oversample(features = x_list[1], labels = data['e'].y, 
            target_edge = target_edge, train_idx = train_idx, edge_indices = edge_indices, args= args, os_mode = 'smote')
        else:
            new_labels, new_train_idx, new_edge_indices, new_target_edge = data['e'].y, train_idx, edge_indices, target_edge
            if os_mode == 'edge_sm':
                edge_em, new_train_idx = x_list[1], new_labels , new_train_idx, new_edge_indices, new_target_edge  = oversample(features =x_list[0], 
                labels = data['e'].y, target_edge = target_edge, train_idx = train_idx, edge_indices = None, args= args, os_mode = 'edge_sm')
        
        outputs = classifier(x_list, new_edge_indices, new_target_edge, x = edge_em, os_mode = os_mode)
        # print(outputs[new_train_idx], outputs[new_train_idx].shape)
        # print(new_labels[new_train_idx], new_labels[new_train_idx].shape)
        new_labels = new_labels.unsqueeze(1).float()
        
        if os_mode == 'reweight':
            weight = x_list[0].new((data['e'].y.max().item()+1)).fill_(1)
            for i in args.im_class_num: weight[i] = 1+args.up_scale
            loss_cls= F.binary_cross_entropy(outputs[new_train_idx], new_labels[new_train_idx], weight=weight)
            del weight
        else:
            loss_cls = F.binary_cross_entropy(outputs[new_train_idx], new_labels[new_train_idx])
        
        if train_mode == 'preO' or train_mode == 'preT' or train_mode == 'pret'  or train_mode == 'preo': 
            loss = sum(loss_de)*args.de_weight + loss_cls
        elif train_mode == 'recon':
            loss = sum(loss_de) * args.de_weight * 10
        else:
            loss = loss_cls
        
        loss.backward()
        
        if train_mode != 'newG':
            optimizer_en.step()
            if train_mode == 'preO' or train_mode == 'preT' or train_mode == 'recon' or train_mode == 'pret'  or train_mode == 'preo':
                for optimizer in optimizer_de:
                    optimizer.step()
                
        optimizer_cls.step()
        
        # if epoch in epochs:      
        acc = accuracy(outputs[new_train_idx].detach(), new_labels[new_train_idx].detach())
        print(f'Epoch [{epoch + 1}/{args.num_epochs}], Loss: {loss.item():.4f}, Accuracy: {acc:.4f}, Edge Accuracy: {edge_ac}')
        evaluate_class_performance(outputs[new_train_idx].cpu().detach(), new_labels[new_train_idx].cpu().detach(), args)
        
        optimizer_en.zero_grad()
        optimizer_cls.zero_grad()
        for optimizer in optimizer_de:
            optimizer.zero_grad()

        for x in x_list: del x
        del loss_cls
        del loss
        del new_labels
        del new_edge_indices
        del new_train_idx
        del outputs

        if val_idx is not None:
            ac, auc, f1, auc_scr, f1_scr = test_smote(data, edge_indices, target_edge, encoder, classifier, decoder_list, val_idx, args = args,
                           dataset='Validation', os_mode='no', train_mode=train_mode)  # Evaluate on the validation dataset
            if epoch in epochs:  
                val_acc_list.append(ac)
                val_auc_list.append(auc)
                val_f1_list.append(f1)
            
        if test_idx is not None:
            ac, auc, f1, auc_scr, f1_scr = test_smote(data, edge_indices, target_edge, encoder, classifier, decoder_list, test_idx, args = args,
                           dataset='Test', os_mode='no', train_mode=train_mode)  # Evaluate on the test dataset
            
            if epoch in epochs:
                print("Poop:", ac,auc,f1) 
                test_acc_list.append(ac)
                test_auc_list.append(auc)
                test_f1_list.append(f1)
            if epoch == 149:
                auc_list = auc_scr
                f1_list = f1_scr
                 
            print()
    print("Finished Training")
    print("Validation Metrics:")
    print("Val_acc_list:", ["{:.4f}".format(val) for val in val_acc_list])
    print("Val_auc_list:", ["{:.4f}".format(val) for val in val_auc_list])
    print("Val_f1_list:", ["{:.4f}".format(val) for val in val_f1_list])
    print("Test Metrics:")
    print("Test_acc_list:", ["{:.4f}".format(val) for val in test_acc_list])
    print("Test_auc_list:", ["{:.4f}".format(val) for val in test_auc_list])
    print("Test_f1_list:", ["{:.4f}".format(val) for val in test_f1_list])
    # return test_acc_list, test_auc_list, test_f1_list, auc_scr, f1_scr

# Test function
def test_smote(data, edge_indices, target_edge, encoder, classifier, decoder_list, test_idx, os_mode, train_mode, args, dataset = "Test"):
    encoder.eval()
    classifier.eval()
    for decoder in decoder_list: decoder.eval()
    loss_de, edge_ac = [], []
    auc_list, f1_list = [], []
    edge_em = None

    with torch.no_grad():
        x_list = encoder(data, os_mode)
        
        if os_mode == 'gsm':
            edge_ac, loss_de, new_edge_indices = het_decode(decoder_list, x_list, edge_indices, 
                ar_edge_indices = None, args = args, train_mode = train_mode, dataset = dataset)
            loss_de = [loss_de[0]*w1, loss_de[1]*w2, loss_de[2]*w3]
        else:
            new_edge_indices = edge_indices
        
        outputs = classifier(x_list, new_edge_indices, target_edge, x = edge_em, os_mode = os_mode)
        new_labels = data['e'].y.unsqueeze(1).float()
        loss_cls =  F.binary_cross_entropy(outputs[test_idx], new_labels[test_idx])
        if train_mode == 'preO' or train_mode == 'preT' or train_mode == 'pret'  or train_mode == 'preo': 
            loss = sum(loss_de) * args.de_weight + loss_cls
        elif train_mode == 'recon':
            loss = torch.tensor(sum(loss_de))  
        else:
            loss = loss_cls            
        
        # print(loss)
        acc = accuracy(outputs[test_idx], new_labels[test_idx]) 
        print(f'{dataset} Loss: {loss.item():.4f}, {dataset} Accuracy: {acc:.4f}, {dataset} Edge Accuracy: {edge_ac}')
        auc, f1, auc_list, f1_list = evaluate_class_performance(outputs[test_idx].cpu(), new_labels[test_idx].cpu(), args)
        
        for x in x_list: del x
        del loss_cls
        del loss
        del new_edge_indices
        
    return acc, auc, f1, auc_list, f1_list


# Function to evalute all decoder related tasks
def het_decode(decoder_list, x_list, edge_indices, ar_edge_indices, args, train_mode, dataset):
    edge_ac = []
    loss_de = []
    edge_list = []
    acc = 0
 
    for i in range(len(decoder_list)):
        
        adj_new = decoder_list[i](x_list[0], x_list[i])
        ori_row_num = args.node_dim[0]
        ori_col_num = args.node_dim[i]
        
        adj_old = torch.zeros((ori_row_num, ori_col_num), dtype = torch.float32, device=x_list[0].device)
        adj_old[edge_indices[i][0], edge_indices[i][1]] = 1.0
        
        if ar_edge_indices is not None:
            adj_ar = torch.zeros((x_list[0].size(0), x_list[i].size(0)), dtype = torch.float32, device=x_list[0].device)
            adj_ar[ar_edge_indices[i][0], ar_edge_indices[i][1]] = 1.0
        else:
            adj_ar = None
  
        # edge_ac.append(F.l1_loss(adj_new[:ori_row_num, :ori_col_num], adj_old, reduction='mean'))
        loss_de.append(edge_loss(adj_new[:ori_row_num, :ori_col_num], adj_old))

        adj_new, acc = adj_gen(adj_new, adj_old, adj_ar, ori_row_num, ori_col_num, dataset)
        adj_new = adj_new.nonzero().t().contiguous()
        edge_ac.append(acc)
        
        if train_mode == 'preO' or train_mode == 'preo':
            edge_list.append(adj_new)
        else:
            edge_list.append(adj_new.detach())
            
    return edge_ac, loss_de, edge_list


def adj_gen(adj_new, adj_old, adj_ar, ori_row_num, ori_col_num, mode):
    threshold = 0.5
    adj_new = (adj_new >= threshold).float()
    
    if adj_ar is not None:
        # print("Adj_new:", adj_new, adj_new.shape, adj_new.sum().item())
        # print("Adj_ar:", adj_ar, adj_ar.shape, adj_ar.sum().item())
        adj_new = torch.mul(adj_ar, adj_new)
        # print("Adj_new 2:", adj_new, adj_new.shape, adj_new.sum().item())
        # print((adj_new == adj_ar).all())

    diff = torch.abs(adj_new[:ori_row_num, :ori_col_num] - adj_old)
    correct_edges = (diff == 0).sum().item()
    total_edges = diff.numel()
    # print(correct_edges, total_edges)
    acc = correct_edges / total_edges
    # print(acc)
    
    if mode == 'Train': 
        adj_new[:ori_row_num, :ori_col_num] = adj_old

    return adj_new, acc


''''

From paper:
0) no- No oversampling, no decoder. Loss = loss_cls
1) upscale- Generate samples by repeating raw data and copy the new adj rows of the synthetic nodes from the parent. Use no decoder. 
Only use classification loss. Loss = loss_cls
2) smote: Do the same thing as upscale but use smote instead of upscale. No decoder. Loss = loss_cls
3) embed-smote: Use smote after encoder. adj_new =adj_old. No decoder. Loss  = loss_cls
4) reweight: No oversampling or decoder. Loss = loss_cls 
---- Use of decoder next (For some reason they eliminated the eliminated the edges between synthetic neighbours) ----
---- In smote, adj_new = decoder(...), adj_up = from parent indices ----
5) recon- Pretrain decoder and encoder together. Loss = loss_de. 
6) newG_cls- Use pretrained encoder and decoder but do not finetune them. Loss = loss_cls
7) recon_newG- Use pretrained encoder and decoder and finetune both. Loss = loss_cls + loss_de * weight
8) opt_new_G- if not, then adj_new is detached .detach() before classification. Which means if we backward propogate 
Loss = loss_cls + loss_de...,  adj and hence the decoder is only updated by loss_de & not by loss_cls which is dependent on detached adj
9) edge_sm = smote on edges

Mine:
0) no
1) upscale 
2) smote
3) embed_sm (Smote, no decoder (adj_new = adj_old), loss = loss_cls)
4) reweight (No smote, decoder, only reweight on loss_cls)
5) recon (Only for training the encoder decoder on loss = loss_de)
6) newG (Encoder, decoder aren't finetuned)
6.5) noFT (Decoder isn't finetuned)
7) preT = no_recon - opt_new_G or recon - opt_new_G  (Decoder is finetuned only loss_de)
8) preO = no_recon + opt_new_G or recon + opt_new_G  (Decoder is finetuned on complete loss)
(5-8) + gsm (graphsmote)
'''