using System;
using System.Security.Cryptography;

namespace ServerHelp.Net
{
    /// <summary>
    /// AES-256 in counter mode with a keystream that keeps running across calls, which is
    /// exactly what MTProto's obfuscated2 transport uses. .NET has no CTR mode, so the
    /// counter block is encrypted with ECB and XOR-ed by hand. Encryption and decryption
    /// are the same operation here.
    /// </summary>
    public sealed class AesCtr : IDisposable
    {
        private readonly ICryptoTransform _ecb;
        private readonly byte[] _counter = new byte[16];
        private readonly byte[] _block = new byte[16];
        private int _used = 16;   // start "empty" so the first call produces a fresh block

        public AesCtr(byte[] key, byte[] iv)
        {
            if (key == null || key.Length != 32) throw new ArgumentException("AES-256 needs a 32 byte key", "key");
            if (iv == null || iv.Length != 16) throw new ArgumentException("counter mode needs a 16 byte iv", "iv");
            var aes = Aes.Create();
            aes.Mode = CipherMode.ECB;
            aes.Padding = PaddingMode.None;
            aes.Key = key;
            _ecb = aes.CreateEncryptor();
            Buffer.BlockCopy(iv, 0, _counter, 0, 16);
        }

        /// <summary>XORs <paramref name="count"/> bytes of keystream into the buffer.</summary>
        public void Xor(byte[] buffer, int offset, int count)
        {
            if (buffer == null) return;
            int end = offset + count;
            for (int i = offset; i < end; i++)
            {
                if (_used == 16)
                {
                    NextBlock();
                    _used = 0;
                }
                buffer[i] ^= _block[_used++];
            }
        }

        private void NextBlock()
        {
            _ecb.TransformBlock(_counter, 0, 16, _block, 0);
            // big endian +1 over the whole 128 bit block, same as the reference implementations
            for (int i = 15; i >= 0; i--)
            {
                if (++_counter[i] != 0) break;
            }
        }

        public void Dispose()
        {
            try { _ecb.Dispose(); } catch { }
            Array.Clear(_counter, 0, _counter.Length);
            Array.Clear(_block, 0, _block.Length);
        }
    }
}
