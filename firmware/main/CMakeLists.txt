set(srcs "app_main.c"
    "display.c"
    "knob.c"
    "ws_client.c"
    "tjpgd.c"
    )

idf_component_register(SRCS ${srcs}
                    INCLUDE_DIRS "."
                    REQUIRES esp_lcd esp_websocket_client esp_wifi esp_netif
                             esp_event nvs_flash esp_timer driver json
                    PRIV_REQUIRES esp_lcd)

# tjpgd.c / tjpgd.h / tjpgdcnf.h 是 TJpgDec R0.03 上游源码，随本仓库一起分发
# 见 tjpgd.c 顶部的版权声明
