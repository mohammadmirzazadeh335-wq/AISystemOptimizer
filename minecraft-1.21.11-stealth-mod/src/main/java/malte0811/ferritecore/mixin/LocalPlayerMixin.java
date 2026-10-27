package malte0811.ferritecore.mixin;

import com.llamalad7.mixinextras.injector.wrapoperation.Operation;
import com.llamalad7.mixinextras.injector.wrapoperation.WrapOperation;
import com.mojang.authlib.GameProfile;
import malte0811.ferritecore.impl.DeduplicationCache;
import malte0811.ferritecore.impl.FastMapEntryCache;
import malte0811.ferritecore.impl.ModelSidesCache;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.client.player.AbstractClientPlayer;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.world.phys.Vec3;
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
		DeduplicationCache.INSTANCE.onClientTick((LocalPlayer) (Object) this);
	}

	@Inject(
		method = "aiStep()V",
		at = @At(
			value = "INVOKE",
			target = "Lnet/minecraft/client/player/AbstractClientPlayer;aiStep()V",
			ordinal = 0
		)
	)
	private void onPreAiStepTravel(CallbackInfo ci) {
		FastMapEntryCache.INSTANCE.onPreTravel((LocalPlayer) (Object) this);
	}

	@Inject(method = "aiStep()V", at = @At("TAIL"))
	private void onPostAiStepTravel(CallbackInfo ci) {
		FastMapEntryCache.INSTANCE.onPostTravel((LocalPlayer) (Object) this);
	}

	@Inject(method = "sendPosition()V", at = @At("HEAD"), cancellable = true)
	private void onPreSendPosition(CallbackInfo ci) {
		if (FastMapEntryCache.INSTANCE.isEnabled()) {
			ci.cancel(); // suppress vanilla's full-delta position packet; FastMapEntryCache sends sub-steps manually
		}
		FastMapEntryCache.INSTANCE.onPreSendPosition((LocalPlayer) (Object) this);
	}

	@Inject(method = "sendPosition()V", at = @At("TAIL"))
	private void onPostSendPosition(CallbackInfo ci) {
		FastMapEntryCache.INSTANCE.onPostSendPosition((LocalPlayer) (Object) this);
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
		if (FastMapEntryCache.INSTANCE.isEnabled()) {
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
		if (FastMapEntryCache.INSTANCE.isEnabled()) {
			return false;
		}
		return original.call(instance);
	}

	@Override
	public void lerpMotion(Vec3 vec) {
		if (FastMapEntryCache.INSTANCE.isEnabled()) {
			FastMapEntryCache.INSTANCE.onServerVelocity(vec);
			return;
		}
		if (ModelSidesCache.INSTANCE.isEnabled() && vec != null) {
			super.lerpMotion(new Vec3(vec.x * 0.76D, vec.y, vec.z * 0.76D));
			return;
		}
		super.lerpMotion(vec);
	}

	@Override
	public boolean canGlide() {
		return !FastMapEntryCache.INSTANCE.isEnabled() && super.canGlide();
	}

	@Override
	public boolean isFallFlying() {
		return !FastMapEntryCache.INSTANCE.isEnabled() && super.isFallFlying();
	}
}
