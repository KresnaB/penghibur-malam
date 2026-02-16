
import asyncio
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.ytdl_source import YTDLSource

class TestYTDLRetry(unittest.IsolatedAsyncioTestCase):
    async def test_retry_success(self):
        """Test that it retries on network error and eventually succeeds."""
        with patch('yt_dlp.YoutubeDL') as mock_ytdl:
            instance = mock_ytdl.return_value
            # Fail twice with DNS error, then succeed
            instance.extract_info.side_effect = [
                Exception("Temporary failure in name resolution"),
                Exception("Connection reset by peer"),
                {'title': 'Test Song', 'webpage_url': 'http://test.com', 'duration': 100}
            ]

            print("\nRunning retry test (expecting 2 failures)...")
            entries, playlist_title = await YTDLSource.get_info("http://test.com")
            
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]['title'], 'Test Song')
            self.assertEqual(instance.extract_info.call_count, 3)
            print("Retry test passed!")

    async def test_retry_failure(self):
        """Test that it eventually fails after max retries."""
        with patch('yt_dlp.YoutubeDL') as mock_ytdl:
            instance = mock_ytdl.return_value
            # Fail 3 times
            instance.extract_info.side_effect = Exception("Temporary failure in name resolution")

            print("\nRunning failure test (expecting 3 failures)...")
            with self.assertRaises(Exception):
                await YTDLSource.get_info("http://test.com")
            
            self.assertEqual(instance.extract_info.call_count, 3)
            print("Failure test passed!")

if __name__ == '__main__':
    unittest.main()
