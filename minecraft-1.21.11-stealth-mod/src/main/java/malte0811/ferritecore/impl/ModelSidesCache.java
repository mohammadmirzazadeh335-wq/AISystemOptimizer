package malte0811.ferritecore.impl;

import java.util.concurrent.ThreadLocalRandom;
import malte0811.ferritecore.ducks.MinecraftClientDuck;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;

public final class ModelSidesCache {
	public static final ModelSidesCache INSTANCE = new ModelSidesCache();

	private static final double MIN_CPS = 30.0D;
	private static final double MAX_CPS = 50.0D;

	private volatile boolean enabled = false;
	private long nextTriggerTimeNs = 0L;
	private double driftCps = 39.5D;
	private int burstStep = 0;

	private ModelSidesCache() {}

	public boolean isEnabled() {
		return enabled;
	}

	public void toggle() {
		setEnabled(!enabled);
	}

	public void setEnabled(boolean state) {
		this.enabled = state;
		this.nextTriggerTimeNs = 0L;
		this.burstStep = 0;
		this.driftCps = 39.5D;
	}

	public void onRenderFrame(Minecraft mc) {
		if (!enabled || mc == null || mc.player == null || mc.level == null) {
			return;
		}
		if (mc.screen != null) {
			return;
		}
		if (mc.options != null && mc.options.keyUse.isDown() && mc.player.isUsingItem()) {
			return;
		}

		long now = System.nanoTime();
		if (now < nextTriggerTimeNs) {
			return;
		}

		nextTriggerTimeNs = now + computeNextDelayNs();

		if (mc instanceof MinecraftClientDuck duck) {
			duck.ferrite$setMissCooldown(0);
			duck.ferrite$triggerAttack();
		}
	}

	public void onClientTick(LocalPlayer player) {
		if (!enabled || player == null) {
			return;
		}
		Minecraft mc = Minecraft.getInstance();
		if (mc instanceof MinecraftClientDuck duck) {
			duck.ferrite$setMissCooldown(0);
		}
	}

	private long computeNextDelayNs() {
		ThreadLocalRandom rng = ThreadLocalRandom.current();
		burstStep++;
		if (burstStep >= 7) {
			burstStep = 0;
			driftCps = rng.nextDouble(33.0D, 46.5D);
		} else {
			driftCps += rng.nextGaussian() * 2.3D;
			if (driftCps < MIN_CPS) {
				driftCps = MIN_CPS + rng.nextDouble(0.4D, 2.2D);
			} else if (driftCps > MAX_CPS) {
				driftCps = MAX_CPS - rng.nextDouble(0.4D, 2.2D);
			}
		}

		double instantCps = driftCps + rng.nextGaussian() * 1.6D;
		if (instantCps < MIN_CPS) {
			instantCps = MIN_CPS;
		} else if (instantCps > MAX_CPS) {
			instantCps = MAX_CPS;
		}

		long baseNs = (long) (1_000_000_000.0D / instantCps);
		long jitterNs = rng.nextLong(-650_000L, 650_000L);
		return Math.max(19_500_000L, baseNs + jitterNs);
	}
}
