#pragma once
#include <stddef.h>
typedef struct cJSON {
    struct cJSON *next, *prev, *child;
    int type;
    char *valuestring;
    int valueint;
    double valuedouble;
    char *string;
} cJSON;
cJSON *cJSON_Parse(const char *v);
cJSON *cJSON_ParseWithLength(const char *v, size_t len);
void cJSON_Delete(cJSON *c);
cJSON *cJSON_GetObjectItem(const cJSON *o, const char *k);
cJSON *cJSON_CreateObject(void);
cJSON *cJSON_CreateArray(void);
cJSON *cJSON_CreateString(const char *s);
void cJSON_AddItemToArray(cJSON *arr, cJSON *item);
void cJSON_AddItemToObject(cJSON *obj, const char *key, cJSON *item);
char *cJSON_PrintUnformatted(const cJSON *c);
int cJSON_IsString(const cJSON *c);
int cJSON_IsNumber(const cJSON *c);
int cJSON_IsArray(const cJSON *c);
int cJSON_IsObject(const cJSON *c);
int cJSON_IsTrue(const cJSON *c);
int cJSON_IsFalse(const cJSON *c);
