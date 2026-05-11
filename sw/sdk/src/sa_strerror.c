#include "spike_accel.h"

__attribute__((visibility("default")))
const char *sa_strerror(sa_status_t status)
{
    switch (status) {
    case SA_OK:               return "OK";
    case SA_ERR_OPEN:         return "ERR_OPEN: device mmap failed";
    case SA_ERR_NO_DEVICE:    return "ERR_NO_DEVICE: /dev/uio0 missing";
    case SA_ERR_WEIGHT_LOAD:  return "ERR_WEIGHT_LOAD: bad weight blob";
    case SA_ERR_DMA:          return "ERR_DMA: DMA engine reported error";
    case SA_ERR_TIMEOUT:      return "ERR_TIMEOUT: inference timeout";
    case SA_ERR_INVALID_ARG:  return "ERR_INVALID_ARG: NULL pointer or bad size";
    case SA_ERR_BUSY:         return "ERR_BUSY: engine in use by another thread";
    default:                  return "ERR_UNKNOWN";
    }
}
