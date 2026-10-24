package malte0811.ferritecore.mixin;

import malte0811.ferritecore.impl.DeduplicationCache;
import net.minecraft.client.KeyboardHandler;
import net.minecraft.client.input.KeyEvent;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(KeyboardHandler.class)
public class KeyboardHandlerMixin {
	@Inject(
		method = "keyPress(JILnet/minecraft/client/input/KeyEvent;)V",
		at = @At("HEAD"),
		cancellable = true
	)
	private void onKeyPress(long windowHandle, int action, KeyEvent event, CallbackInfo ci) {
		if (event != null && DeduplicationCache.INSTANCE.onKeyInput(event.key(), action, event.modifiers())) {
			ci.cancel();
		}
	}
}
