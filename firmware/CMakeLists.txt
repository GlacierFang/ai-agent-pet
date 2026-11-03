# ai-agent-pet 固件 —— ESP32-S3 桌面宠物屏
#
# 显示管线：服务端整帧渲染 JPEG → 设备 TJpgDec 按 MCU 解码 → SPI DMA 直刷
# 协议见 ../../docs/协议.md，构建见 ../../docs/固件构建.md
cmake_minimum_required(VERSION 3.16)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ai-agent-pet)
