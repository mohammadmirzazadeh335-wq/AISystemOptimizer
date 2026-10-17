package net.optifabric.ferrite.mixin;

import net.minecraft.client.Minecraft;
import net.minecraft.world.entity.Entity;
import net.optifabric.ferrite.bridge.MinecraftAccessor;
import net.optifabric.ferrite.module.AutoClickerModule;
import net.optifabric.ferrite.module.XRayModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(Minecraft.class)
public abstract class MinecraftMixin implements MinecraftAccessor {
	@Shadow
	protected int missTime;

	@Shadow
	private boolean startAttack() {
		throw new AssertionError();
	}

	@Override
	public void ferrite$setMissTime(int missTime) {
		this.missTime = missTime;
	}

	@Override
	public boolean ferrite$invokeStartAttack() {
		this.missTime = 0;
		return this.startAttack();
	}

	@Inject(method = "runTick(Z)V", at = @At("HEAD"), require = 0)
	private void onRunTick(boolean renderLevel, CallbackInfo ci) {
		AutoClickerModule.INSTANCE.onRenderFrame((Minecraft) (Object) this);
	}

	@Inject(method = "startAttack()Z", at = @At("HEAD"), require = 0)
	private void onPreStartAttack(CallbackInfoReturnable<Boolean> cir) {
		if (AutoClickerModule.INSTANCE.isEnabled()) {
			this.missTime = 0;
		}
	}

	@Inject(
		method = "shouldEntityAppearGlowing(Lnet/minecraft/world/entity/Entity;)Z",
		at = @At("HEAD"),
		cancellable = true
	)
	private void onShouldEntityAppearGlowing(Entity entity, CallbackInfoReturnable<Boolean> cir) {
		if (XRayModule.INSTANCE.shouldHighlightEntity(entity)) {
			cir.setReturnValue(true);
		}
	}

	@Inject(method = "allowsTelemetry()Z", at = @At("HEAD"), cancellable = true)
	private void onAllowsTelemetry(CallbackInfoReturnable<Boolean> cir) {
		cir.setReturnValue(false);
	}

	@Inject(method = "extraTelemetryAvailable()Z", at = @At("HEAD"), cancellable = true)
	private void onExtraTelemetryAvailable(CallbackInfoReturnable<Boolean> cir) {
		cir.setReturnValue(false);
	}
}
