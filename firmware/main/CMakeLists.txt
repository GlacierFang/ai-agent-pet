set(srcs "app_main.c"
    "display.c"
    "knob.c"
    "screen_text.c"
    "provision.c"
    "ws_client.c"
    "ota.c"
    "tjpgd.c"
    "game/game_runtime.c"
    "game/game_comp.c"
    "game/game_phys.c"
    "game/game_draw.c"
    "game/game_pack.c"
    "game/game_menu.c"
    "game/game_glyph.c"
    )

idf_component_register(SRCS ${srcs}
                    INCLUDE_DIRS "." "game"
                    REQUIRES esp_lcd esp_websocket_client esp_wifi esp_netif esp_event esp_http_server esp_app_format nvs_flash esp_timer esp_driver_spi esp_driver_gpio esp_system esp_hw_support esp_psram heap log json spiffs vfs
                    PRIV_REQUIRES esp_lcd)

# tjpgd.c / tjpgd.h / tjpgdcnf.h 是 TJpgDec R0.03 上游源码，随本仓库一起分发
# 见 tjpgd.c 顶部的版权声明
