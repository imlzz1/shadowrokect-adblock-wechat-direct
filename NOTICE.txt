# NOTICE / 来源与许可说明

本仓库包含两类东西，许可是分开的：

## 1. 构建脚本（MIT）

`scripts/`、`tests/`、`.github/` 下的代码采用 **MIT License**，见根目录 `LICENSE`。

## 2. 生成的规则配置（CC BY-SA 4.0）

`dist/shadowrocket-wechat.conf` 以及发布到 `release` 分支的配置，是在以下项目的基础上
**下载、合并、排序、去重、增删规则**后生成的衍生作品：

- [Johnshall/Shadowrocket-ADBlock-Rules-Forever](https://github.com/Johnshall/Shadowrocket-ADBlock-Rules-Forever)
  - 原项目许可：**CC BY-SA 4.0**
  - 许可全文：https://creativecommons.org/licenses/by-sa/4.0/
  - 本项目对原规则做了：重新排序、去重、后缀合并、删除与微信直连冲突的条目、
    增加微信直连与微信广告拦截规则。

因此，**生成的配置按 CC BY-SA 4.0 分发**。配置头部保留了原项目地址和构建时间；
如果你再分发修改后的配置，请保留署名，并以相同许可共享。

## 3. 微信域名清单

`config/wechat-direct.list`、`config/wechat-ad.list` 是根据微信公开服务域名、
实际请求记录以及社区公开列表交叉整理出的**域名事实清单**，不是从某个项目复制的代码。
整理时参考了（仅用于交叉核对域名是否存在、是否属于广告）：

- [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script)
- [k6nfmm7dbr-commits/wechat-lite](https://github.com/k6nfmm7dbr-commits/wechat-lite)（MIT）
- [TG-Twilight/AWAvenue-Ads-Rule](https://github.com/TG-Twilight/AWAvenue-Ads-Rule)
- [QingRex/LoonKissSurge](https://github.com/QingRex/LoonKissSurge)

如果你认为某些域名清单的整理方式需要调整，欢迎提交 Issue。

## 4. 免责声明

规则可能因为上游更新、域名变化或误判而失效/误杀。使用前请自行评估，并保留关闭配置、
切换回原配置的手段。作者不对使用本规则造成的任何损失负责。
