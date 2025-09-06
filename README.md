<!--
 * @Date: 2025-09-06 14:09:13
 * @LastEditors: 马艳龙 myl86898244@gmail.com
 * @LastEditTime: 2025-09-06 14:19:50
 * @FilePath: \telegram_to_alink\README.md
-->
# telegram_to_alink

docker build --network=host -t telegram-alist-bot .

docker run -d  --network=host   --name tg_bot   --env-file ./config.env   -v /root/telegram_videos:/app/videos   telegram-alist-bot