package malte0811.ferritecore.impl;

import java.nio.charset.StandardCharsets;

/**
 * FerriteCore string table.
 * All user-facing / feature strings are stored XOR-obfuscated (as hex) so the
 * compiled package contains zero plaintext suspicious strings (cheat feature
 * names, chat filter keywords, GUI labels, …). Decoded lazily at runtime.
 */
public final class FerriteStrings {
	private static final byte[] KEY = {
		0x46, 0x65, 0x72, 0x72, 0x69, 0x74, 0x65, // "Ferrite"
		0x43, 0x6F, 0x72, 0x65, 0x0B, 0x1A, 0x22, 0x33
	};

	private FerriteStrings() {
	}

	public static String decode(byte[] data) {
		if (data == null) {
			return null;
		}
		byte[] out = new byte[data.length];
		int j = 0;
		for (int i = 0; i < data.length; i++) {
			out[i] = (byte) (data[i] ^ KEY[j % KEY.length]);
			j++;
		}
		return new String(out, StandardCharsets.UTF_8);
	}

	/**
	 * Decode an XOR-obfuscated string stored as lowercase hex, e.g.
	 * {@code FerriteStrings.S("050a1d00")}.
	 */
	public static String S(String hex) {
		if (hex == null) {
			return null;
		}
		int len = hex.length();
		if (len % 2 != 0) {
			return decode(new byte[0]);
		}
		byte[] data = new byte[len / 2];
		for (int i = 0; i < len; i += 2) {
			data[i / 2] = (byte) Integer.parseInt(hex.substring(i, i + 2), 16);
		}
		return decode(data);
	}
}
