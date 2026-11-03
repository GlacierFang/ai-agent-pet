# ai-agent-pet 固件 —— ESP32-S3 桌面宠物屏
#
# 显示管线：服务端整帧渲染 JPEG → 设备 TJpgDec 按 MCU 解码 → SPI DMA 直刷
# 协议见 ../../docs/协议.md，构建见 ../../docs/固件构建.md
#
# project 名 = petd，决定产物名 build/petd.bin（app 分区镜像）。
# 整片镜像是 IDF 自己产出的 build/merged-binary.bin；UF2 是 build/uf2.bin。
cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(petd)
