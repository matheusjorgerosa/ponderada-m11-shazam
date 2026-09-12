/* Stub de host. Ver tests/host/README.md. */
#ifndef ESP_ERR_H
#define ESP_ERR_H
typedef int esp_err_t;
#define ESP_OK                0
#define ESP_FAIL             -1
#define ESP_ERR_INVALID_SIZE  0x104
static inline const char *esp_err_to_name(esp_err_t e) { (void)e; return "stub"; }
#endif
