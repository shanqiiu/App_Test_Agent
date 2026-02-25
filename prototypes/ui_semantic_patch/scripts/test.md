 python run_pipeline.py --screenshot ../data/原图/影视剧集类-内容歧义、重复/腾讯视频.jpg --instruction "页面底部弹出选集弹窗" --anomaly-mode=dialog_blocking --gt-category "内容歧义、重复" --gt-sample "部分信息重复.jpg" --output ./output/页面底部弹出选集弹窗
 
python run_pipeline.py --screenshot "../data/原图/个人主页类-控件点击弹窗/抖音原图01.jpg" --instruction " 作品控件下方有列表弹窗 内容为最热、最新" --gt-category "弹窗覆盖原UI" --gt-sample "弹出提示.jpg" --output ./output/作品控件下方有列表弹窗内容为最热、最新 --anomaly-mode dialog

python run_pipeline.py --screenshot "../data/原图/app首页类-开屏广告弹窗/携程旅行01.jpg" --instruction "开启微信、支付宝提示通知的弹窗" --gt-category "弹窗覆盖原UI" --gt-sample "关闭按钮干扰.jpg" --output ./output/开启微信、支付宝提示通知的弹窗 --anomaly-mode dialog

python run_pipeline.py --screenshot "../data/原图/外卖类优惠信息干扰/饿了么.jpg" --instruction "生成底部固定优惠券弹窗遮挡商品列表，内容“本店优惠，满20减7”" --gt-category "弹窗覆盖原UI" --gt-sample "商品下方存在遮挡.jpg" --output ./output/生成底部固定优惠券弹窗遮挡商品列表，内容“本店优惠，满20减7” --anomaly-mode dialog

python run_pipeline.py --screenshot "../data/原图/外卖类优惠信息干扰/饿了么.jpg" --instruction "底部价格处上方生成Tips遮罩，内容为到店自取更便宜" --gt-category "弹窗覆盖原UI" --gt-sample "使用教程遮挡2.jpg" --output ./output/底部Tips遮罩 --anomaly-mode dialog