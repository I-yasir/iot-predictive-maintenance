// Host-side check of the firmware generator (no Arduino): prints N cycles as CSV.
//   g++ -std=c++17 -O2 -Iinclude test/host_generator_test.cpp -o /tmp/gen && /tmp/gen 12345 0 50
#include <cstdio>
#include <cstdlib>

#include "profile_fd001.h"
#include "pdm_generator.h"

int main(int argc, char** argv) {
  uint32_t seed = argc > 1 ? (uint32_t)strtoul(argv[1], nullptr, 10) : 12345u;
  PdmMode mode = (argc > 2 && atoi(argv[2]) == 1) ? PDM_MODE_DISTRIBUTION : PDM_MODE_TRAJECTORY;
  int n = argc > 3 ? atoi(argv[3]) : 10;
  PdmGenerator g(seed, mode);
  double v[PDM_N_CHANNELS];
  for (int i = 0; i < n; i++) {
    int c = g.next(v);
    printf("%d,%d,%d", c, g.life(), g.trueRemaining());
    for (int j = 0; j < PDM_N_CHANNELS; j++) printf(",%.4f", v[j]);
    printf("\n");
  }
  return 0;
}
