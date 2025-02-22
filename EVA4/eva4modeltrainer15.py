from tqdm import tqdm_notebook, tnrange
from eva4modelstats import ModelStats
import torch.nn.functional as F
import torch
import torchvision
from torch.utils.tensorboard import SummaryWriter
from loss import ssim, msssim,compute_errors
from utils import saveresults, show
import gc
import numpy as np



# https://github.com/tqdm/tqdm
class Train:
  def __init__(self, model, dataloader, optimizer, stats, scheduler=None, criterion1=None, criterion2=None, L1lambda = 0, tb=None):
    self.model = model
    self.dataloader = dataloader
    self.optimizer = optimizer
    self.scheduler = scheduler
    self.stats = stats
    self.L1lambda = L1lambda
    self.criterion1 = criterion1
    self.criterion2 = criterion2
    self.tb = tb
    self.images_data = [[],[],[],[]]

  def run(self):
    self.model.train()
    pbar = tqdm_notebook(enumerate(self.dataloader))
    for batch_idx, data in pbar:
      # get samples
      fgbg, mask, depth = data['fgbg'].to(self.model.device), data['mask'].to(self.model.device), data['depth'].to(self.model.device)

      # Init
      self.optimizer.zero_grad()
      
      
      mask_pred, depth_pred = self.model(fgbg)
     

      # Calculate loss
      if self.criterion1 is not None:
        loss1 = self.criterion1(mask_pred, mask)
        

        m_ssim = torch.clamp((1 - msssim(mask_pred, mask, normalize=True)) * 0.5, 0, 1)
    
        loss1 = (0.84 * m_ssim) + (0.16 * loss1)
      if self.criterion2 is not None:
        loss2 = self.criterion2(depth_pred, depth)
        

      d_ssim = torch.clamp( 1 - msssim(depth_pred, depth, normalize=True)*0.5, 0, 1)
      
    
      loss2 = (0.84 * d_ssim) + (0.16 * loss2)
      #print(loss1.item(), loss2.item(), d_ssim.item())
      loss = 2 * loss1 + loss2

      #Implementing L1 regularization
      if self.L1lambda > 0:
        reg_loss = 0.
        for param in self.model.parameters():
          reg_loss += torch.sum(param.abs())
        loss += self.L1lambda * reg_loss
      
      n = self.stats.get_batches()
      if n%500 == 0:
        self.tb.add_scalar('loss/train', loss.item(), n)
      
      if (n+1) % 30 == 0:#Need to change this later
        grid = torchvision.utils.make_grid(mask_pred.detach().cpu(), nrow=8, normalize=False)
        self.tb.add_image('imagesmask', grid, n)
        grid = torchvision.utils.make_grid(depth_pred.detach().cpu(), nrow=8, normalize=False)
        self.tb.add_image('imagesdepth', grid, n)
      
      
        saveresults(fgbg.detach().cpu(), "./plots/fgbg"+str(n+1)+".jpg", normalize=True)
        saveresults(mask.detach().cpu(), "./plots/orimask"+str(n+1)+".jpg")
        saveresults(depth.detach().cpu(), "./plots/oridepth"+str(n+1)+".jpg")
        saveresults(mask_pred.detach().cpu(), "./plots/predmask"+str(n+1)+".jpg")
        saveresults(depth_pred.detach().cpu(), "./plots/preddepth"+str(n+1)+".jpg")
	
		

      # Backpropagation
      loss.backward()
      self.optimizer.step()
      for i in range(len(fgbg)):
        self.images_data[0].append(mask[i].detach().cpu())
        self.images_data[1].append(depth[i].detach().cpu())
        self.images_data[2].append(mask_pred[i].detach().cpu())
        self.images_data[3].append(depth_pred[i].detach().cpu())
      # Update pbar-tqdm
      
      lr = 0.0
      if self.scheduler:
        lr = self.scheduler.get_last_lr()[0]
      else:
        # not recalling why i used sekf.optimizer.lr_scheduler.get_last_lr[0]
        lr = self.optimizer.param_groups[0]['lr']
      
      #lr =  if self.scheduler else (self.optimizer.lr_scheduler.get_last_lr()[0] if self.optimizer.lr_scheduler else self.optimizer.param_groups[0]['lr'])
      #print('lr for this batch:", lr)

      self.stats.add_batch_train_stats(loss.item(), 0, len(data), lr)
      pbar.set_description(self.stats.get_latest_batch_desc())
      if self.scheduler:
        self.scheduler.step()
    predictions1 = np.stack(self.images_data[2], axis=0)
    testSetDepths1 = np.stack(self.images_data[0], axis=0)
    predictions2 = np.stack(self.images_data[1], axis=0)
    testSetDepths2 = np.stack(self.images_data[3], axis=0)
    e1 = compute_errors(predictions1, testSetDepths1)
    e2 = compute_errors(predictions2, testSetDepths2)
    print("train Quantitative measures (a1, a2, a3, abs_rel, rmse, log_10)  1.mask 2.depth")
    print(*e1)
    print(*e2)
	
class Test:
  def __init__(self, model, dataloader, stats, scheduler=None, criterion1=None, criterion2=None, tb=None):
    self.model = model
    self.dataloader = dataloader
    self.stats = stats
    self.scheduler = scheduler
    self.loss=0.0
    self.criterion1 = criterion1
    self.criterion2 = criterion2
    self.tb = tb
    self.images_data = [[],[],[],[]]

  def run(self):
    self.model.eval()
    with torch.no_grad():
        
        for batch_idx, data in enumerate(self.dataloader):
            fgbg, mask, depth =  data['fgbg'].to(self.model.device), data['mask'].to(self.model.device), data['depth'].to(self.model.device)
            
            mask_pred, depth_pred = self.model(fgbg)
            for i in range(len(fgbg)):
              self.images_data[0].append(mask[i].detach().cpu())
              self.images_data[1].append(depth[i].detach().cpu())
              self.images_data[2].append(mask_pred[i].detach().cpu())
              self.images_data[3].append(depth_pred[i].detach().cpu())
            # Calculate loss
            if self.criterion1 is not None:
              loss1 = self.criterion1(mask_pred, mask)
            m_ssim = torch.clamp((1 - ssim(mask_pred, mask)) * 0.5, 0, 1)
    
            loss1 = (0.84 * m_ssim) + (0.16 * loss1)

            if self.criterion2 is not None:
                loss2 = self.criterion2(depth_pred, depth)

            d_ssim = torch.clamp((1 - ssim(depth_pred, depth)) * 0.5, 0, 1)
    
            loss2 = (0.84 * d_ssim) + (0.16 * loss2)

            self.loss = 2 * loss1 + loss2

            if batch_idx == 0:
              
              inp = fgbg.detach().cpu()
              orimp = mask.detach().cpu()
              mp = mask_pred.detach().cpu()
              oridp = depth.detach().cpu()
              dp = depth_pred.detach().cpu()
              print("First batch in testing fgbg, (mask, predicted mask), (depth, predicted depth)")
              show(inp[:8,:,:,:], normalize=True)
              mdinp = torch.cat([orimp[:8,:,:,:], mp[:8,:,:,:], oridp[:8,:,:,:], dp[:8,:,:,:]],dim=0)
              show(mdinp)
                       
            
            self.stats.add_batch_test_stats(self.loss.item(), 0, len(data))
        
        if self.scheduler and isinstance(self.scheduler, torch.optim.lr_scheduler.ReduceLROnPlateau):
              #print("hello yes i am ")
              self.scheduler.step(self.loss)
    predictions1 = np.stack(self.images_data[2], axis=0)
    testSetDepths1 = np.stack(self.images_data[0], axis=0)
    predictions2 = np.stack(self.images_data[1], axis=0)
    testSetDepths2 = np.stack(self.images_data[3], axis=0)
    e1 = compute_errors(predictions1, testSetDepths1)
    e2 = compute_errors(predictions2, testSetDepths2)
    print("test Quantitative measures (a1, a2, a3, abs_rel, rmse, log_10)  1.mask 2.depth")
    print(*e1)
    print(*e2)
            
class ModelTrainer:
  def __init__(self, model, optimizer, train_loader, test_loader, statspath, scheduler=None, batch_scheduler=False, criterion1=None, criterion2=None, L1lambda = 0):
    self.tb = SummaryWriter()
    self.model = model
    
    #x = torch.rand(1,3,128,128)
    #self.tb.add_graph(self.model, x.to(self.model.device), x.to(self.model.device))
    self.scheduler = scheduler
    self.batch_scheduler = batch_scheduler
    self.optimizer = optimizer
    self.stats = ModelStats(model, statspath)
    self.criterion1 = criterion1
    self.criterion2 = criterion2
    self.train = Train(model, train_loader, optimizer, self.stats, self.scheduler if self.batch_scheduler else None, criterion1=criterion1, criterion2=criterion2, L1lambda=L1lambda, tb=self.tb)
    self.test = Test(model, test_loader, self.stats,self.scheduler, criterion1=criterion1, criterion2=criterion2, tb=self.tb)
	
  

  def run(self, epochs=10):
    pbar = tqdm_notebook(range(1, epochs+1), desc="Epochs")
    for epoch in pbar:
      gc.collect()
      self.train.run()
      self.test.run()
      lr = self.optimizer.param_groups[0]['lr']
      self.stats.next_epochmaskdepth(lr)
      pbar.write(self.stats.get_epoch_desc())
      # need to ake it more readable and allow for other schedulers
      if self.scheduler and not self.batch_scheduler and not isinstance(self.scheduler, torch.optim.lr_scheduler.ReduceLROnPlateau):
        self.scheduler.step()
        print(self.scheduler.get_last_lr())
      pbar.write(f"Learning Rate = {lr:0.6f}")
      self.tb.close()

    # save stats for later lookup
    #self.stats.save()
