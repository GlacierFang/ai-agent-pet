#pragma once
#include <stddef.h>
typedef struct {
    const char *base_path;
    size_t max_files;
    const char *partition_label;
    bool format_if_mount_failed;
} esp_vfs_spiffs_conf_t;
esp_err_t esp_vfs_spiffs_register(const esp_vfs_spiffs_conf_t *conf);
esp_err_t esp_vfs_spiffs_unregister(const char *partition_label);
