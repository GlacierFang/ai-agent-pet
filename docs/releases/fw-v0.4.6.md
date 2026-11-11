## 0.4.6

修 RGB565 高低字节颠倒。

### 改动

只动了一个宏 —— `firmware/main/display.c` 里的 `LCD_DATA_ENDIAN`:

```c
-#define LCD_DATA_ENDIAN    LCD_RGB_DATA_ENDIAN_BIG
+#define LCD_DATA_ENDIAN    LCD_RGB_DATA_ENDIAN_LITTLE
```

IDF v5.5 自己的 `esp_lcd_panel_st7789.c` 里有这段逻辑:
```c
if ((panel_dev_config->data_endian) == LCD_RGB_DATA_ENDIAN_LITTLE) {
    st7789->ramctl_val_2 |= ST7789_DATA_LITTLE_ENDIAN_BIT;
}
```

也就是置 ST7789 的 `RAMCTL` 小端位 —— 语义就是 RGB565 高低字节交换。

```LCD_INVERT_COLOR``` 保持 `true`(v0.4.5 的反相修复保留)。

### 烧录

刷 `merged-binary.bin`(整片镜像,0x0 起)。只接 PC,不接充电头 —— DevKitC-1 两个 USB 口的 5V 是通的。

```bash
python3 -m esptool --chip esp32s3 --port /dev/ttyUSB0 write-flash 0x0 merged-binary.bin
```

⚠️ 这版仍未经实机验证 —— 编译在 CI 里通过,但没在实板子上跑过。

**Full Changelog**: https://github.com/GlacierFang/ai-agent-pet/compare/fw-v0.4.5...fw-v0.4.6
