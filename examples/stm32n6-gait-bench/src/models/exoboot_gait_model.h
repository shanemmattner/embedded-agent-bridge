/*
 * Exoboot Gait Phase Estimator — INT8 TFLite model header
 *
 * Source: github.com/maxshep/exoboot-ml-gait-state-estimator (Apache 2.0)
 * Architecture: Conv1D x3 + 2 Dense heads (gait_phase, stance_swing)
 * Input: (1, 44, 8) int8 — 44 timesteps of 8 IMU channels
 */
#ifndef EXOBOOT_GAIT_MODEL_H
#define EXOBOOT_GAIT_MODEL_H

extern const unsigned char g_exoboot_gait_model[];
extern const int g_exoboot_gait_model_len;

#endif
