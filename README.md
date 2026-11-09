# 精易论坛

精易签到脚本（青龙面板），Python 重写版。

站点已从 bbs.125.la 迁移到 **bbs.ijingyi.com**（老域名 301 跳转），脚本默认直连新域名，可用 `JY_HOST` 覆盖。

## 部署

青龙面板 → 脚本管理 → 放入 `jingyi_qiandao.py`（通知依赖同目录的 `notify.py`）→ 环境变量 → 新建：

| 变量 | 必填 | 说明 |
|---|---|---|
| `JY_COOKIE` | 是 | `formhash@cookie`；多账号用换行分隔，可写 `备注#formhash@cookie` |
| `JY_QDXQ` | 否 | 签到心情，默认 `kx`（可选 kx / ng / ymwl / ch） |
| `JY_SAY` | 否 | 签到留言，默认空 |
| `JY_RETRY` | 否 | 单账号最多尝试次数，默认 3 |
| `JY_HOST` | 否 | 站点域名，默认 `bbs.ijingyi.com`，站点再换域名改这里 |
| `JY_DEBUG` | 否 | 填 `1` 打印接口原始返回，排错用 |

## 抓包注意

- post_data 里的 formhash 要与 Cookie 对应，脚本也会自动从签到页刷新；
- Cookie 里的 `__ancc_tokenV2` 删掉，脚本每次会自己取；
- Cookie 只需保留 `xxx_2132_` 开头的那几段。

## 行为说明

- 成功：输出“签到成功”及累计签到、本月签到、总奖励、上次签到等字段；
- 已签到：签到页出现“已签到 / 连续签到”时直接判为已签到，不再重复提交；
- Cookie 失效：接口返回“您需要先登录才能继续本操作”时判定，退出码 1。
