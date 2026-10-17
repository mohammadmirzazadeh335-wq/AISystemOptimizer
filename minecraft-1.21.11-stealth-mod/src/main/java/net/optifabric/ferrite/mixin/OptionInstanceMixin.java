package net.optifabric.ferrite.mixin;

import java.util.Objects;
import java.util.function.Consumer;
import net.minecraft.client.Minecraft;
import net.minecraft.client.OptionInstance;
import net.optifabric.ferrite.bridge.OptionInstanceDuck;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(OptionInstance.class)
public class OptionInstanceMixin<T> implements OptionInstanceDuck<T> {
	@Shadow
	T value;

	@Shadow
	@Final
	private Consumer<T> onValueUpdate;

	@SuppressWarnings("unchecked")
	@Inject(method = "get()Ljava/lang/Object;", at = @At("HEAD"), cancellable = true)
	private void onGet(CallbackInfoReturnable<T> cir) {
		if (!XRayModule.INSTANCE.isEnabled()) {
			return;
		}
		Minecraft mc = Minecraft.getInstance();
		if (mc != null && mc.options != null && mc.screen == null && (Object) this == mc.options.gamma()) {
			cir.setReturnValue((T) Double.valueOf(16.0D));
		}
	}

	@Override
	public void setUncheckedValue(T newValue) {
		if (!Minecraft.getInstance().isRunning()) {
			value = newValue;
			return;
		}
		if (!Objects.equals(value, newValue)) {
			value = newValue;
			onValueUpdate.accept(value);
		}
	}
}
