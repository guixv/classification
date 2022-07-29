import torch
import torch.nn as nn


def drop_path(x, drop_prob: float = 0., training: bool = False):
    if drop_prob == 0. or not training:
        return x
    keep_prob = 1 - drop_prob
    shape = (x.shape[0],) + (1,) * (x.ndim - 1)  # work with diff dim tensors, not just 2D ConvNets
    random_tensor = keep_prob + torch.rand(shape, dtype=x.dtype, device=x.device)
    random_tensor.floor_()  # binarize
    output = x.div(keep_prob) * random_tensor
    return output


class DropPath(nn.Module):
    """Drop paths (Stochastic Depth) per sample  (when applied in main path of residual blocks).
    """

    def __init__(self, drop_prob=None):
        super(DropPath, self).__init__()
        self.drop_prob = drop_prob

    def forward(self, x):
        return drop_path(x, self.drop_prob, self.training)


class PatchEmbedding(nn.Module):
    def __init__(self, img_size=120, patch_size=16, in_channel=3, embed_size=768, norm_layer=nn.LayerNorm):
        super(PatchEmbedding, self).__init__()
        self.img_size = (img_size, img_size)
        self.patch_size = (patch_size, patch_size)
        self.num_patch = (img_size // patch_size) * (img_size * patch_size)
        self.feature = nn.Conv2d(in_channels=in_channel, out_channels=embed_size, kernel_size=self.patch_size,
                                 stride=self.patch_size)
        self.norm = norm_layer

    def forward(self, x):
        B, C, H, W = x.shape
        if H != self.img_size[0] or W != self.img_size[1]:
            print("输入图像大小{} x {} 与model {}x{}不符".format(H, W, x.shape[0], x.shape[1]))
            exit(1)
        x = self.feature(x)
        # flatten: [B, C, H, W] -> [B, C, HW]
        # transpose: [B, C, HW] -> [B, HW, C]
        x = x.flatten(2)
        x = x.transpose(1, 2)
        x = self.norm(x)
        return x


class Attention(nn.Module):
    def __init__(self, dim, num_heads=8, qkv_bias=False, qk_scale=None, atten_drop_rate=0., feature_dop_rate=0.):
        super(Attention, self).__init__()
        self.num_heads = num_heads
        head_dim = dim / num_heads
        self.scale = qk_scale or head_dim ** -0.5
        self.qkv = nn.Linear(dim, dim * 3, bias=False)
        self.attenDrop = nn.Dropout(atten_drop_rate)
        self.featureDrop = nn.Dropout(feature_dop_rate)
        self.feature = nn.Linear(dim, dim)

    def forward(self, x):
        # [batch_size, num_patches + 1, total_embed_dim]
        B, N, C = x.shape
        qkv = self.qkv(x)
        # [batch_size, num_patches + 1, 3 * total_embed_dim]
        qkv = qkv.reshape(B, N, 3, self.num_heads, C // self.num_heads)
        qkv = qkv.permute(2, 0, 3, 1, 4)
        # [batch_size, num_heads, num_patches + 1, embed_dim_per_head]

        q, k, v = qkv[0], qkv[1], qkv[2]

        k = k.transpose(-2, -1)
        attention = (q @ k) * self.scale
        # [batch_size, num_heads, num_patches + 1, num_patches + 1]
        attention = attention.softmax(dim=-1)
        attention = self.attenDrop(attention)

        x = attention @ v
        # [batch_size, num_heads, num_patches + 1, embed_dim_per_head]
        x = x.transpose(1, 2)
        # transpose: [batch_size, num_patches + 1, num_heads, embed_dim_per_head]
        x = x.reshape(B, N, C)
        x = self.feature(x)
        x = self.attenDrop(x)
        return x


class Mlp(nn.Module):
    def __init__(self, in_channel, hidden_channel, out_channel=None, active_layer=nn.GELU, drop_pro=0.):
        super(Mlp, self).__init__()
        out_channel = in_channel or out_channel
        hidden_channel = in_channel or hidden_channel
        self.fc1 = nn.Linear(in_features=in_channel, out_features=hidden_channel)
        self.act = active_layer()
        self.fc2 = nn.Linear(in_features=hidden_channel, out_features=out_channel)
        self.dropout = nn.Dropout(drop_pro)

    def forward(self, x):
        x = self.fc1(x)
        x = self.act(x)
        x = self.dropout(x)
        x = self.fc2(x)
        x = self.dropout(x)

        return x


class Block(nn.Module):
    def __init__(self, dim, num_heads, qkv_bias=False, qk_scale=None, atten_drop_rate=0.,
                 feature_drop_rate=0., path_drop_prob=0., mlp_ratio=4.):
        super(Block, self).__init__()
        self.norm1 = nn.LayerNorm(dim)
        self.atten = Attention(dim=dim, num_heads=num_heads, qkv_bias=qkv_bias, qk_scale=qk_scale,
                               atten_drop_rate=atten_drop_rate, feature_dop_rate=feature_drop_rate)
        self.drop_path = DropPath(drop_prob=path_drop_prob)
        self.norm2 = nn.LayerNorm(dim)
        mlp_hidden_dim = dim * mlp_ratio
        self.mlp = Mlp(in_channel=dim, hidden_channel=mlp_hidden_dim, out_channel=dim, active_layer=nn.GELU,
                       drop_pro=feature_drop_rate)

    def forward(self, x):
        x = self.norm1(x)
        x = self.atten(x)
        x = x + self.drop_path(x)

        x = self.norm2(x)
        x = self.mlp(x)
        x = x + self.drop_path(x)

        return x


class ViT(nn.Module):
    def __init__(self):
        super(ViT, self).__init__()