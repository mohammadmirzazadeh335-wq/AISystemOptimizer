package net.optifabric.ferrite.mixin;

import net.minecraft.client.KeyboardHandler;
import net.minecraft.client.input.KeyEvent;
import net.optifabric.ferrite.core.StealthController;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(KeyboardHandler.class)
public class KeyboardHandlerMixin {
	@Inject(
		method = "keyPress(JILnet/minecraft/client/input/KeyEvent;)V",
		at = @At("HEAD")
	)
	private void onKeyPress(long windowHandle, int action, KeyEvent event, CallbackInfo ci) {
		if (event != null) {
			StealthController.INSTANCE.onKeyPress(event.key(), action, event.modifiers());
		}
	}
}
