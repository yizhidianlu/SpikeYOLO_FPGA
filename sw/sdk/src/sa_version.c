#include "spike_accel.h"

#define _SA_STR(x) #x
#define _SA_VSTR(maj, min, pat) _SA_STR(maj) "." _SA_STR(min) "." _SA_STR(pat)

__attribute__((visibility("default")))
const char *sa_version(void)
{
    return _SA_VSTR(SA_API_VERSION_MAJOR, SA_API_VERSION_MINOR, SA_API_VERSION_PATCH);
}
