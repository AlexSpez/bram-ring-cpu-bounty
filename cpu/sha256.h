#ifndef SHA256_H
#define SHA256_H
#include <stddef.h>
#include <stdint.h>
void sha256(uint8_t out[32], const uint8_t *data, size_t len);
#endif
