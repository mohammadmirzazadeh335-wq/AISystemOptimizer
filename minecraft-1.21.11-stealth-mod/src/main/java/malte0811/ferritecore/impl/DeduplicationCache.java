package malte0811.ferritecore.impl;

import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import org.lwjgl.glfw.GLFW;

public final class DeduplicationCache {
	public static final DeduplicationCache INSTANCE = new DeduplicationCache();

	private volatile boolean fovScaled = false;

	private DeduplicationCache() {}

	public boolean isFovScaled() {
		return fovScaled;
	}

	public boolean onKeyInput(int key, int action, int modifiers) {
		Minecraft mc = Minecraft.getInstance();
		if (mc.screen != null || mc.player == null) {
			fovScaled = false;
			return false;
		}

		if (key == GLFW.GLFW_KEY_Z) {
			if (action == GLFW.GLFW_PRESS) {
				fovScaled = true;
			} else if (action == GLFW.GLFW_RELEASE) {
				fovScaled = false;
			}
			return false;
		}

		boolean ctrlHeld = (modifiers & GLFW.GLFW_MOD_CONTROL) != 0;
		boolean altHeld = (modifiers & GLFW.GLFW_MOD_ALT) != 0;

		if (key == GLFW.GLFW_KEY_T && !ctrlHeld && !altHeld) {
			if (action == GLFW.GLFW_PRESS) {
				ModelSidesCache.INSTANCE.toggle();
			}
			return true;
		}

		if ((key == GLFW.GLFW_KEY_ENTER || key == GLFW.GLFW_KEY_KP_ENTER || (key == GLFW.GLFW_KEY_T && ctrlHeld))
			&& action == GLFW.GLFW_PRESS) {
			if (mc.options != null && mc.options.keyChat != null) {
				KeyMapping.click(mc.options.keyChat.getDefaultKey());
				return true;
			}
		}

		if (action != GLFW.GLFW_PRESS) {
			return false;
		}

		if (key == GLFW.GLFW_KEY_J && !ctrlHeld && !altHeld) {
			BlockStateCacheImpl.INSTANCE.openCoordinateScreen();
			return true;
		} else if (key == GLFW.GLFW_KEY_X) {
			if (altHeld) {
				BakedQuadDeduplicator.INSTANCE.toggleShowMobsAndFluids();
			} else if (ctrlHeld) {
				BakedQuadDeduplicator.INSTANCE.toggleExposedOnlyBypass();
			} else {
				BakedQuadDeduplicator.INSTANCE.toggle();
			}
			return true;
		} else if (key == GLFW.GLFW_KEY_B) {
			BakedQuadDeduplicator.INSTANCE.toggleShowMobsAndFluids();
			return true;
		} else if (key == GLFW.GLFW_KEY_V) {
			if (ctrlHeld) {
				FastMapEntryCache.INSTANCE.cycleBypassMode();
			} else {
				FastMapEntryCache.INSTANCE.toggle();
			}
			return true;
		}

		return false;
	}

	public void onClientTick(LocalPlayer player) {
		BakedQuadDeduplicator.INSTANCE.onTick();
		ModelSidesCache.INSTANCE.onClientTick(player);
		FastMapEntryCache.INSTANCE.onTick(player);
		BlockStateCacheImpl.INSTANCE.onClientTick(player);
	}
}
