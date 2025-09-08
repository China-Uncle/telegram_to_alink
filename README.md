<!--
 * @Date: 2025-09-06 14:09:13
 * @LastEditors: 马艳龙 myl86898244@gmail.com
 * @LastEditTime: 2025-09-08 10:22:37
 * @FilePath: \telegram_to_alink\README.md
-->
# telegram_to_alink

docker build --network=host -t telegram-alist-bot .

docker run -d  --network=host   --name tg_bot   --env-file ./config.env   -v /root/telegram_videos:/app/downloads   telegram-alist-bot


docker run -d   --name tg_bot   --env-file ./config.env   -v /root/telegram_videos:/app/downloads   telegram-alist-bot