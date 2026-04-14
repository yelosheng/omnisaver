from services.threads_service import ThreadsService, ThreadsServiceError


def test_url_detection():
    assert ThreadsService.is_valid_threads_url('https://www.threads.com/@daftchi/post/DUF-iPhDNfA')
    assert ThreadsService.is_valid_threads_url('https://www.threads.net/@foo/post/ABC123')
    assert not ThreadsService.is_valid_threads_url('https://instagram.com/p/ABC')
    assert not ThreadsService.is_valid_threads_url('https://twitter.com/foo')


def test_extract_post_id():
    assert ThreadsService.extract_post_id('https://www.threads.com/@daftchi/post/DUF-iPhDNfA?xmt=123') == 'DUF-iPhDNfA'


def test_extract_url_from_share_text():
    share_text = 'Check this out https://www.threads.com/@daftchi/post/DUF-iPhDNfA?xmt=123 interesting'
    assert ThreadsService.extract_url_from_share_text(share_text) == 'https://www.threads.com/@daftchi/post/DUF-iPhDNfA'
