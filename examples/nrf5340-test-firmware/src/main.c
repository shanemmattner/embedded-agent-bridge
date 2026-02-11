/*
 * EAB Test Firmware — Fake sensor data over RTT
 *
 * Outputs two sine waves (90° out of phase), a noisy "temperature" reading,
 * and rotating sensor states. Designed to exercise the EAB RTT bridge.
 */

#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>
#include <math.h>
#include <stdlib.h>

LOG_MODULE_REGISTER(eab_test, LOG_LEVEL_INF);

#define TICK_MS       200
#define TWO_PI        6.2831853f

/* Sensor states */
static const char *states[] = {"IDLE", "SAMPLING", "PROCESSING", "TRANSMITTING"};
#define NUM_STATES ARRAY_SIZE(states)

int main(void)
{
	uint32_t tick = 0;
	int state_idx = 0;
	float temp_base = 24.5f;

	LOG_INF("*** EAB Test Firmware v1.0 ***");
	LOG_INF("Streaming fake sensor data at %d ms intervals", TICK_MS);

	while (1) {
		/* Two sine waves, 90 degrees out of phase */
		float phase = TWO_PI * (float)tick / 50.0f;
		float sine_a = sinf(phase);
		float sine_b = sinf(phase + (TWO_PI / 4.0f));

		/* Fake temperature: slow drift + small noise */
		float drift = sinf(TWO_PI * (float)tick / 500.0f) * 2.0f;
		float noise = ((float)(rand() % 100) - 50.0f) / 100.0f;
		float temp = temp_base + drift + noise;

		/* Cycle through states every 2 seconds */
		if (tick % 10 == 0) {
			state_idx = (state_idx + 1) % NUM_STATES;
			LOG_INF("STATE: %s", states[state_idx]);
		}

		/* Log sensor readings — integer encoding for RTT efficiency
		 * Multiply floats by 100 and cast to int for LOG_INF
		 * (Zephyr LOG_INF doesn't support %%f on all backends)
		 */
		int sa = (int)(sine_a * 100);
		int sb = (int)(sine_b * 100);
		int ti = (int)(temp * 100);

		LOG_INF("DATA: sine_a=%d.%02d sine_b=%d.%02d temp=%d.%02d",
			sa / 100, abs(sa % 100),
			sb / 100, abs(sb % 100),
			ti / 100, abs(ti % 100));

		tick++;
		k_msleep(TICK_MS);
	}

	return 0;
}
