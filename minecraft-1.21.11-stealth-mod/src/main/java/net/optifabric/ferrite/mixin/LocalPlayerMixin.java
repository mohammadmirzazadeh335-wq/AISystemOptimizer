package net.optifabric.ferrite.mixin;

import com.llamalad7.mixinextras.injector.wrapoperation.Operation;
import com.llamalad7.mixinextras.injector.wrapoperation.WrapOperation;
import com.mojang.authlib.GameProfile;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.AbstractClientPlayer;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.phys.Vec3;
import net.optifabric.ferrite.core.StealthController;
import net.optifabric.ferrite.module.FlightModule;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(LocalPlayer.class)
public abstract class LocalPlayerMixin extends AbstractClientPlayer {
	private LocalPlayerMixin(ClientLevel level, GameProfile profile) {
		super(level, profile);
	}

	@Inject(
		method = "tick()V",
		at = @At(
			value = "INVOKE",
			target = "Lnet/minecraft/client/player/AbstractClientPlayer;tick()V",
			ordinal = 0
		)
	)
	private void onTick(CallbackInfo ci) {
		StealthController.INSTANCE.onClientTick((LocalPlayer) (Object) this);
	}

	@Inject(method = "sendPosition()V", at = @At("HEAD"))
	private void onPreSendPosition(CallbackInfo ci) {
		FlightModule.INSTANCE.onPreSendPosition((LocalPlayer) (Object) this);
	}

	@Inject(method = "sendPosition()V", at = @At("TAIL"))
	private void onPostSendPosition(CallbackInfo ci) {
		FlightModule.INSTANCE.onPostSendPosition((LocalPlayer) (Object) this);
	}

	@WrapOperation(
		method = "aiStep()V",
		at = @At(
			value = "INVOKE",
			target = "Lnet/minecraft/client/player/LocalPlayer;isSlowDueToUsingItem()Z",
			ordinal = 0
		)
	)
	private boolean onAiStepSlowCheck(LocalPlayer instance, Operation<Boolean> original) {
		if (FlightModule.INSTANCE.isEnabled()) {
			return false;
		}
		return original.call(instance);
	}

	@WrapOperation(
		method = "modifyInput(Lnet/minecraft/world/phys/Vec2;)Lnet/minecraft/world/phys/Vec2;",
		at = @At(
			value = "INVOKE",
			target = "Lnet/minecraft/client/player/LocalPlayer;isUsingItem()Z",
			ordinal = 0
		)
	)
	private boolean onModifyInputSlowCheck(LocalPlayer instance, Operation<Boolean> original) {
		if (FlightModule.INSTANCE.isEnabled()) {
			return false;
		}
		return original.call(instance);
	}

	@Override
	public float maxUpStep() {
		if (FlightModule.INSTANCE.isEnabled()) {
			return 1.25F;
		}
		return super.maxUpStep();
	}

	@Override
	public void lerpMotion(Vec3 vec) {
		if (FlightModule.INSTANCE.isEnabled()) {
			return;
		}
		super.lerpMotion(vec);
	}

	@Override
	public boolean canGlide() {
		return !FlightModule.INSTANCE.isEnabled() && super.canGlide();
	}

	@Override
	public boolean isFallFlying() {
		return !FlightModule.INSTANCE.isEnabled() && super.isFallFlying();
	}

	@Override
	protected float getFlyingSpeed() {
		if (FlightModule.INSTANCE.isEnabled()) {
			return 0.0F;
		}
		return super.getFlyingSpeed();
	}

	@Override
	public boolean isInWater() {
		if (FlightModule.INSTANCE.isEnabled()) {
			return false;
		}
		return super.isInWater();
	}
}
