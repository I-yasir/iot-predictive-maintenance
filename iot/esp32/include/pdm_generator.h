// PdM-Live synthetic telemetry generator — portable C++ (no Arduino dependencies).
// Used by the ESP32 firmware AND by the host test (g++), and mirrored line-for-line by
// iot/pdm_iot/simulator/virtual_esp32.py so a given seed produces the same values everywhere.
//
// Modes (docs/05 §10):
//   TRAJECTORY   : real unseen test engine + small Gaussian noise (scale PDM_NOISE_SCALE_TRAJECTORY * sigma)
//   DISTRIBUTION : life ~ lognormal(train lives); value = healthy mean + drift(remaining cycles) + sigma * N(0,1)
#ifndef PDM_GENERATOR_H
#define PDM_GENERATOR_H

#include <math.h>
#include <stdint.h>

#ifndef PDM_PROFILE_NAME
#error "include a generated profile header (e.g. profile_fd001.h) before pdm_generator.h"
#endif

enum PdmMode { PDM_MODE_TRAJECTORY = 0, PDM_MODE_DISTRIBUTION = 1 };

class PdmGenerator {
 public:
  explicit PdmGenerator(uint32_t seed, PdmMode mode) : state_(seed | 1u), mode_(mode) { newLife(); }

  // Fill out[PDM_N_CHANNELS] (settings first, then sensors) for the next cycle.
  // Returns the cycle number (1-based). When a life ends, the next call starts a new life at cycle 1.
  int next(double* out) {
    if (cycle_ >= life_) newLife();
    cycle_++;
    for (int j = 0; j < PDM_N_CHANNELS; j++) {
      double z = gauss();  // always draw, keeps every implementation in lock-step
      if (mode_ == PDM_MODE_TRAJECTORY) {
        double base = PDM_TRAJECTORY[(cycle_ - 1) * PDM_N_CHANNELS + j];
        double noise = (j < PDM_N_SETTINGS) ? 0.0 : PDM_NOISE_SCALE_TRAJECTORY * PDM_NOISE_SIGMA[j] * z;
        out[j] = round4(base + noise);
      } else {
        int remaining = life_ - cycle_;
        out[j] = round4(PDM_HEALTHY_MEAN[j] + drift(remaining, j) + PDM_NOISE_SIGMA[j] * z);
      }
    }
    return cycle_;
  }

  int cycle() const { return cycle_; }
  int life() const { return life_; }
  bool endOfLife() const { return cycle_ >= life_; }
  // Ground truth for test harnesses: remaining cycles after the current one.
  int trueRemaining() const {
    return mode_ == PDM_MODE_TRAJECTORY ? (life_ - cycle_) + PDM_TRAJ_TRUE_RUL_END : life_ - cycle_;
  }

 private:
  uint32_t state_;
  PdmMode mode_;
  int cycle_ = 0;
  int life_ = 0;

  uint32_t xorshift32() {
    uint32_t x = state_;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    state_ = x;
    return x;
  }
  // uniform in (0, 1]: 24 random bits
  double uniform() { return ((double)(xorshift32() >> 8) + 1.0) / 16777216.0; }
  double gauss() {
    double u1 = uniform();
    double u2 = uniform();
    return sqrt(-2.0 * log(u1)) * cos(6.283185307179586 * u2);
  }
  static double round4(double v) { return round(v * 10000.0) / 10000.0; }

  static double drift(int remaining, int j) {
    if (remaining < 0) remaining = 0;
    int maxR = (PDM_DRIFT_LEN - 1) * PDM_DRIFT_STEP;
    if (remaining >= maxR) return PDM_DRIFT[(PDM_DRIFT_LEN - 1) * PDM_N_CHANNELS + j];
    int i = remaining / PDM_DRIFT_STEP;
    double f = (double)(remaining - i * PDM_DRIFT_STEP) / PDM_DRIFT_STEP;
    double a = PDM_DRIFT[i * PDM_N_CHANNELS + j];
    double b = PDM_DRIFT[(i + 1) * PDM_N_CHANNELS + j];
    return a + f * (b - a);
  }

  void newLife() {
    cycle_ = 0;
    if (mode_ == PDM_MODE_TRAJECTORY) {
      life_ = PDM_TRAJ_LEN;
    } else {
      double l = exp(PDM_LIFE_LOG_MEAN + PDM_LIFE_LOG_STD * gauss());
      life_ = (int)round(l);
      if (life_ < PDM_LIFE_MIN) life_ = PDM_LIFE_MIN;
    }
  }
};

#endif  // PDM_GENERATOR_H
