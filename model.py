import math
import torch
import torch.nn.functional as F
import torch.nn as nn

import pandas as pd
from tqdm import tqdm

from hyperparams import hp
from dataset import TextMelDataset, text_mel_collate_fn
from pad_mask_utils import get_mask_from_sequence_lengths
from text_utils import text_to_seq

# https://github.com/NVIDIA/tacotron2/blob/master/model.py
# https://github.com/NVIDIA/tacotron2/blob/master/layers.py

class EncoderBlock(nn.Module):
  def __init__(self):
    super(EncoderBlock, self).__init__()
    self.norm_1 = nn.LayerNorm(
      normalized_shape=hp.embedding_size
    )
    self.attn = torch.nn.MultiheadAttention(
      embed_dim=hp.embedding_size,
      num_heads=4,
      dropout=0.1,
      batch_first=True
    )
    self.dropout_1 = torch.nn.Dropout(0.1)

    self.norm_2 = nn.LayerNorm(
      normalized_shape=hp.embedding_size
    )

    self.linear_1 = nn.Linear(
      hp.embedding_size, 
      hp.dim_feedforward
    )

    self.dropout_2 = torch.nn.Dropout(0.1)
    self.linear_2 = nn.Linear(
      hp.dim_feedforward, 
      hp.embedding_size
    )
    self.dropout_3 = torch.nn.Dropout(0.1)
    

  def forward(
    self, 
    x,
    attn_mask = None, 
    key_padding_mask = None
  ):
    x_out = self.norm_1(x)
    x_out, _ = self.attn(
      query=x_out, 
      key=x_out, 
      value=x_out,
      attn_mask=attn_mask,
      key_padding_mask=key_padding_mask
    )
    x_out = self.dropout_1(x_out)
    x = x + x_out    

    x_out = self.norm_2(x) 

    x_out = self.linear_1(x_out)
    x_out = F.relu(x_out)
    x_out = self.dropout_2(x_out)
    x_out = self.linear_2(x_out)
    x_out = self.dropout_3(x_out)

    x = x + x_out
    
    return x


class DecoderBlock(nn.Module):
  def __init__(self):
    super(DecoderBlock, self).__init__()
    self.norm_1 = nn.LayerNorm(
      normalized_shape=hp.embedding_size
    )
    self.self_attn = torch.nn.MultiheadAttention(
      embed_dim=hp.embedding_size,
      num_heads=4,
      dropout=0.1,
      batch_first=True
    )
    self.dropout_1 = torch.nn.Dropout(0.1)

    self.norm_2 = nn.LayerNorm(
      normalized_shape=hp.embedding_size
    )
    self.attn = torch.nn.MultiheadAttention(
      embed_dim=hp.embedding_size,
      num_heads=4,
      dropout=0.1,
      batch_first=True
    )    
    self.dropout_2 = torch.nn.Dropout(0.1)

    self.norm_3 = nn.LayerNorm(
      normalized_shape=hp.embedding_size
    )

    self.linear_1 = nn.Linear(
      hp.embedding_size, 
      hp.dim_feedforward
    )
    self.dropout_3 = torch.nn.Dropout(0.1)
    self.linear_2 = nn.Linear(
      hp.dim_feedforward, 
      hp.embedding_size
    )
    self.dropout_4 = torch.nn.Dropout(0.1)


  def forward(
    self,     
    x,
    memory,
    x_attn_mask = None, 
    x_key_padding_mask = None,
    memory_attn_mask = None,
    memory_key_padding_mask = None
  ):
    x_out, _ = self.self_attn(
      query=x, 
      key=x, 
      value=x,
      attn_mask=x_attn_mask,
      key_padding_mask=x_key_padding_mask
    )
    x_out = self.dropout_1(x_out)
    x = self.norm_1(x + x_out)
     
    x_out, _ = self.attn(
      query=x,
      key=memory,
      value=memory,
      attn_mask=memory_attn_mask,
      key_padding_mask=memory_key_padding_mask
    )
    x_out = self.dropout_2(x_out)
    x = self.norm_2(x + x_out)

    x_out = self.linear_1(x)
    x_out = F.relu(x_out)
    x_out = self.dropout_3(x_out)
    x_out = self.linear_2(x_out)
    x_out = self.dropout_4(x_out)
    x = self.norm_3(x + x_out)

    return x


class EncoderPreNet(nn.Module):
  def __init__(self):
    super(EncoderPreNet, self).__init__()
    
    self.embedding = nn.Embedding(
        num_embeddings=hp.text_num_embeddings,
        embedding_dim=hp.encoder_embedding_size
    )

    self.linear_1 = nn.Linear(
      hp.encoder_embedding_size, 
      hp.encoder_embedding_size
    )

    self.linear_2 = nn.Linear(
      hp.encoder_embedding_size, 
      hp.embedding_size
    )

    self.conv_1 = nn.Conv1d(
      hp.encoder_embedding_size, 
      hp.encoder_embedding_size,
      kernel_size=hp.encoder_kernel_size, 
      stride=1,
      padding=int((hp.encoder_kernel_size - 1) / 2), 
      dilation=1
    )
    self.bn_1 = nn.BatchNorm1d(
      hp.encoder_embedding_size
    )
    self.dropout_1 = torch.nn.Dropout(0.5)

    self.conv_2 = nn.Conv1d(
      hp.encoder_embedding_size, 
      hp.encoder_embedding_size,
      kernel_size=hp.encoder_kernel_size, 
      stride=1,
      padding=int((hp.encoder_kernel_size - 1) / 2), 
      dilation=1
    )
    self.bn_2 = nn.BatchNorm1d(
      hp.encoder_embedding_size
    )
    self.dropout_2 = torch.nn.Dropout(0.5)

    self.conv_3 = nn.Conv1d(
      hp.encoder_embedding_size, 
      hp.encoder_embedding_size,
      kernel_size=hp.encoder_kernel_size, 
      stride=1,
      padding=int((hp.encoder_kernel_size - 1) / 2), 
      dilation=1
    )
    self.bn_3 = nn.BatchNorm1d(
      hp.encoder_embedding_size
    )
    self.dropout_3 = torch.nn.Dropout(0.5)    

  def forward(self, text):
    x = self.embedding(text) # (N, T, E)
    x = self.linear_1(x)

    x = x.transpose(2, 1) # (N, E, T) 

    x = self.conv_1(x)
    x = self.bn_1(x)
    x = F.relu(x)
    x = self.dropout_1(x)

    x = self.conv_2(x)
    x = self.bn_2(x)
    x = F.relu(x)
    x = self.dropout_2(x)
    
    x = self.conv_3(x)
    x = self.bn_3(x)    
    x = F.relu(x)
    x = self.dropout_3(x)

    x = x.transpose(1, 2) # (N, T, E)
    x = self.linear_2(x)

    return x


class PostNet(nn.Module):
  def __init__(self):
    super(PostNet, self).__init__()  
    
    self.conv_1 = nn.Conv1d(
      hp.mel_freq, 
      hp.postnet_embedding_size,
      kernel_size=hp.postnet_kernel_size, 
      stride=1,
      padding=int((hp.postnet_kernel_size - 1) / 2), 
      dilation=1
    )
    self.bn_1 = nn.BatchNorm1d(
      hp.postnet_embedding_size
    )
    self.dropout_1 = torch.nn.Dropout(0.5)

    self.conv_2 = nn.Conv1d(
      hp.postnet_embedding_size, 
      hp.postnet_embedding_size,
      kernel_size=hp.postnet_kernel_size, 
      stride=1,
      padding=int((hp.postnet_kernel_size - 1) / 2), 
      dilation=1
    )
    self.bn_2 = nn.BatchNorm1d(
      hp.postnet_embedding_size
    )
    self.dropout_2 = torch.nn.Dropout(0.5)

    self.conv_3 = nn.Conv1d(
      hp.postnet_embedding_size, 
      hp.postnet_embedding_size,
      kernel_size=hp.postnet_kernel_size, 
      stride=1,
      padding=int((hp.postnet_kernel_size - 1) / 2), 
      dilation=1
    )
    self.bn_3 = nn.BatchNorm1d(
      hp.postnet_embedding_size
    )
    self.dropout_3 = torch.nn.Dropout(0.5)

    self.conv_4 = nn.Conv1d(
      hp.postnet_embedding_size, 
      hp.postnet_embedding_size,
      kernel_size=hp.postnet_kernel_size, 
      stride=1,
      padding=int((hp.postnet_kernel_size - 1) / 2), 
      dilation=1
    )
    self.bn_4 = nn.BatchNorm1d(
      hp.postnet_embedding_size
    )
    self.dropout_4 = torch.nn.Dropout(0.5)


    self.conv_5 = nn.Conv1d(
      hp.postnet_embedding_size, 
      hp.postnet_embedding_size,
      kernel_size=hp.postnet_kernel_size, 
      stride=1,
      padding=int((hp.postnet_kernel_size - 1) / 2), 
      dilation=1
    )
    self.bn_5 = nn.BatchNorm1d(
      hp.postnet_embedding_size
    )
    self.dropout_5 = torch.nn.Dropout(0.5)


    self.conv_6 = nn.Conv1d(
      hp.postnet_embedding_size, 
      hp.mel_freq,
      kernel_size=hp.postnet_kernel_size, 
      stride=1,
      padding=int((hp.postnet_kernel_size - 1) / 2), 
      dilation=1
    )
    self.bn_6 = nn.BatchNorm1d(hp.mel_freq)
    self.dropout_6 = torch.nn.Dropout(0.5)


  def forward(self, x):
    # x - (N, L, FREQ)

    x = x.transpose(2, 1) # (N, FREQ, L)

    x = self.conv_1(x)
    x = self.bn_1(x)
    x = torch.tanh(x)
    x = self.dropout_1(x) # (N, POSNET_DIM, L)

    x = self.conv_2(x)
    x = self.bn_2(x)
    x = torch.tanh(x)
    x = self.dropout_2(x) # (N, POSNET_DIM, L)

    x = self.conv_3(x)
    x = self.bn_3(x)
    x = torch.tanh(x)
    x = self.dropout_3(x) # (N, POSNET_DIM, L)    

    x = self.conv_4(x)
    x = self.bn_4(x)
    x = torch.tanh(x)
    x = self.dropout_4(x) # (N, POSNET_DIM, L)    

    x = self.conv_5(x)
    x = self.bn_5(x)
    x = torch.tanh(x)
    x = self.dropout_5(x) # (N, POSNET_DIM, L)

    x = self.conv_6(x)
    x = self.bn_6(x)
    x = self.dropout_6(x) # (N, FREQ, L)

    x = x.transpose(1, 2)

    return x


class DecoderPreNet(nn.Module):
  def __init__(self):
    super(DecoderPreNet, self).__init__()
    self.linear_1 = nn.Linear(
      hp.mel_freq, 
      hp.embedding_size
    )

    self.linear_2 = nn.Linear(
      hp.embedding_size, 
      hp.embedding_size
    )

  def forward(self, x):
    x = self.linear_1(x)
    x = F.relu(x)
    
    x = F.dropout(x, p=0.5, training=True)

    x = self.linear_2(x)
    x = F.relu(x)    
    x = F.dropout(x, p=0.5, training=True)

    return x    


class TransformerTTS(nn.Module):
  def __init__(self, device="cuda"):
    super(TransformerTTS, self).__init__()

    self.encoder_prenet = EncoderPreNet()
    self.decoder_prenet = DecoderPreNet()
    self.postnet = PostNet()

    self.pos_encoding = nn.Embedding(
        num_embeddings=hp.max_mel_time, 
        embedding_dim=hp.embedding_size
    )

    self.encoder_block_1 = EncoderBlock()
    self.encoder_block_2 = EncoderBlock()
    self.encoder_block_3 = EncoderBlock()

    self.decoder_block_1 = DecoderBlock()
    self.decoder_block_2 = DecoderBlock()
    self.decoder_block_3 = DecoderBlock()

    self.linear_1 = nn.Linear(hp.embedding_size, hp.mel_freq) 
    self.linear_2 = nn.Linear(hp.embedding_size, 1)

    self.norm_memory = nn.LayerNorm(
      normalized_shape=hp.embedding_size
    )


  def forward(
    self, 
    text, 
    text_len,
    mel, 
    mel_len
  ):  
    
    N = text.shape[0]
    S = text.shape[1]
    L = mel.shape[1]

    self.src_key_padding_mask = torch.zeros(
        (N, S),
        device=text.device
    ).masked_fill(
      ~get_mask_from_sequence_lengths(
        text_len,
        max_length=S
      ),
      float("-inf")
    )
    
    self.src_mask = torch.zeros(
      (S, S),
      device=text.device
    ).masked_fill(
      torch.triu(
          torch.full(
              (S, S), 
              True,
              dtype=torch.bool
          ), 
          diagonal=1
      ).to(text.device),       
      float("-inf")
    )

    self.tgt_key_padding_mask = torch.zeros(
      (N, L),
      device=mel.device
    ).masked_fill(
      ~get_mask_from_sequence_lengths(
        mel_len,
        max_length=L
      ),
      float("-inf")
    )

    self.tgt_mask = torch.zeros(
      (L, L),
      device=mel.device
    ).masked_fill(
      torch.triu(
          torch.full(
              (L, L), 
              True,
              device=mel.device,
              dtype=torch.bool
          ), 
          diagonal=1
      ),       
      float("-inf")
    )

    self.memory_mask = torch.zeros(
      (L, S),
      device=mel.device
    ).masked_fill(
      torch.triu(
          torch.full(
              (L, S), 
              True,
              device=mel.device,
              dtype=torch.bool
          ), 
          diagonal=1          
      ),       
      float("-inf")
    )    


    text_x = self.encoder_prenet(text) # (N, S, E)    
    
    pos_codes = self.pos_encoding(
      torch.arange(hp.max_mel_time).to(mel.device)
    ) # (MAX_S_L, E)

    S = text_x.shape[1]
    text_x = text_x + pos_codes[:S]
    # dropout after pos encoding?

    text_x = self.encoder_block_1(
      text_x, 
      attn_mask = self.src_mask, 
      key_padding_mask = self.src_key_padding_mask
    )
    text_x = self.encoder_block_2(
      text_x, 
      attn_mask = self.src_mask, 
      key_padding_mask = self.src_key_padding_mask
    )    
    text_x = self.encoder_block_3(
      text_x, 
      attn_mask = self.src_mask, 
      key_padding_mask = self.src_key_padding_mask
    ) # (N, S, E)

    text_x = self.norm_memory(text_x)
    

    L = mel.shape[1] 
    mel_x = self.decoder_prenet(mel) # (N, L, E)    
    mel_x = mel_x + pos_codes[:L]
    # dropout after pos encoding?

    mel_x = self.decoder_block_1(
      x=mel_x,
      memory=text_x,
      x_attn_mask=self.tgt_mask, 
      x_key_padding_mask=self.tgt_key_padding_mask,
      memory_attn_mask=self.memory_mask,
      memory_key_padding_mask=self.src_key_padding_mask
    )

    mel_x = self.decoder_block_2(
      x=mel_x,
      memory=text_x,
      x_attn_mask=self.tgt_mask, 
      x_key_padding_mask=self.tgt_key_padding_mask,
      memory_attn_mask=self.memory_mask,
      memory_key_padding_mask=self.src_key_padding_mask
    )

    mel_x = self.decoder_block_3(
      x=mel_x,
      memory=text_x,
      x_attn_mask=self.tgt_mask, 
      x_key_padding_mask=self.tgt_key_padding_mask,
      memory_attn_mask=self.memory_mask,
      memory_key_padding_mask=self.src_key_padding_mask
    ) # (N, L, E)

    mel_linear = self.linear_1(mel_x) # (N, L, FREQ)
    mel_postnet = self.postnet(mel_linear) # (N, L, FREQ)
    mel_postnet = mel_linear + mel_postnet # (N, L, FREQ)
    gate = self.linear_2(mel_x) # (N, L, 1)

    bool_mel_mask = self.tgt_key_padding_mask.ne(0).unsqueeze(-1).repeat(
      1, 1, hp.mel_freq
    )

    mel_linear = mel_linear.masked_fill(
      bool_mel_mask,
      0
    )

    mel_postnet = mel_postnet.masked_fill(
      bool_mel_mask,
      0      
    )

    gate = gate.masked_fill(
      bool_mel_mask[:, :, 0].unsqueeze(-1),
      1e3
    ).squeeze(2)
    
    return mel_postnet, mel_linear, gate 



  @torch.no_grad()
  def inference(self, text, max_length=800, gate_threshold = 0.5, with_tqdm = True):
    self.eval()    
    self.train(False)
    text_lengths = torch.tensor(text.shape[1]).unsqueeze(0).cuda()
    N = 1
    SOS = torch.zeros((N, 1, hp.mel_freq), device="cuda")
    
    mel_padded = SOS
    mel_lengths = torch.tensor(1).unsqueeze(0).cuda()
    gate_outputs = torch.FloatTensor([]).to(text.device)

    if with_tqdm:
      iters = tqdm(range(max_length))
    else:
      iters = range(max_length)

    for _ in iters:
      mel_postnet, mel_linear, gate = self(
        text, 
        text_lengths,
        mel_padded,
        mel_lengths
      )

      mel_padded = torch.cat(
        [
          mel_padded,      
          mel_postnet[:, -1:, :]
        ], 
        dim=1
      )
      if torch.sigmoid(gate[:,-1]) > gate_threshold:      
        break
      else:
        gate_outputs = torch.cat([gate_outputs, gate[:,-1:]], dim=1)
        mel_lengths = torch.tensor(mel_padded.shape[1]).unsqueeze(0).cuda()

    return mel_postnet, gate_outputs




def test_with_dataloader():
  df = pd.read_csv(hp.csv_path)
  dataset = TextMelDataset(df)  
  loader = torch.utils.data.DataLoader(
      dataset, 
      num_workers=1, 
      shuffle=False,
      sampler=None, 
      batch_size=4,
      pin_memory=True, 
      drop_last=True,       
      collate_fn=text_mel_collate_fn
  )

  model = TransformerTTS().cuda()
  
  for batch in loader:
    text_padded, \
    text_lengths, \
    mel_padded, \
    gate_padded, \
    mel_lengths = batch

    text_padded = text_padded.cuda()
    text_lengths = text_lengths.cuda()
    mel_padded = mel_padded.cuda()
    gate_padded = gate_padded.cuda()
    mel_lengths = mel_lengths.cuda()

    post, mel, gate = model(
      text_padded, 
      text_lengths,
      mel_padded,
      mel_lengths
    )
    print("post:", post.shape) 
    print("mel:", mel.shape) 
    print("gate:", gate.shape)

    break


def test_inference():
  model = TransformerTTS().cuda()
  text = text_to_seq("Hello, world.").unsqueeze(0).cuda()
  mel_postnet, gate = model.inference(text, gate_threshold=1e3)
  print("mel_postnet:", mel_postnet.shape)
  print("gate:", gate.shape)


def test_torchview():
  from torchview import draw_graph

  df = pd.read_csv(hp.csv_path)
  dataset = TextMelDataset(df)  

  loader = torch.utils.data.DataLoader(
      dataset, 
      num_workers=1, 
      shuffle=False,
      sampler=None, 
      batch_size=4,
      pin_memory=True, 
      drop_last=True,       
      collate_fn=text_mel_collate_fn
  )

  model = TransformerTTS().cuda()
  
  for batch in loader:
    text_padded, \
    text_lengths, \
    mel_padded, \
    gate_padded, \
    mel_lengths = batch

    text_padded = text_padded.cuda()
    text_lengths = text_lengths.cuda()
    mel_padded = mel_padded.cuda()
    gate_padded = gate_padded.cuda()
    mel_lengths = mel_lengths.cuda()

    post, mel, gate = model(
      text_padded, 
      text_lengths,
      mel_padded,
      mel_lengths
    )

    print("Input:")
    print("text_padded: ", text_padded.dtype)
    print("text_lengths: ", text_lengths.dtype)
    print("mel_padded: ", mel_padded.dtype)
    print("mel_lengths: ", mel_lengths.dtype)

    print("\nOutput:")
    print("post: ", post.dtype)
    print("mel: ", mel.dtype)
    print("gate: ", gate.dtype)

    inputs = [
      text_padded,
      text_lengths,
      mel_padded,
      mel_lengths
    ]

    model_graph = draw_graph(
      model, 
      #input_size=[it.shape for it in inputs], 
      input_data=inputs,
      device='meta',
      save_graph=True,
      filename="model.png",
      depth=1
    )

    #model_graph.visual_graph

    break


if __name__ == "__main__":
  test_torchview()