from dl_plus import ytdl
from dl_plus.extractor import Extractor, ExtractorError, ExtractorPlugin


int_or_none, parse_iso8601, urljoin = ytdl.import_from(
    'utils', ['int_or_none', 'parse_iso8601', 'urljoin'])


__version__ = '0.3.0'


plugin = ExtractorPlugin(__name__)


class WASDTVBaseExtractor(Extractor):

    DLP_BASE_URL = r'https?://(www\.)?wasd\.tv/'

    _API_BASE = 'https://wasd.tv/api/'
    _THUMBNAIL_SIZES = ('small', 'medium', 'large')

    def _fetch(self, *path, description, item_id, **kwargs):
        """
        Fetch the resource using WASD.TV API.

        The positional arguments are the parts of the resource path relative
        to the _API_BASE.

        The following keyword arguments are required by this method:
            * item_id -- item identifier (for logging purposes).
            * description -- human-readable resource description (for logging
            purposes).

        Any additional keyword arguments are passed directly to
        the _download_json method.
        """
        response = self._download_json(
            urljoin(self._API_BASE, '/'.join(path)),
            item_id,
            note=f'Downloading {description} metadata',
            errnote=f'Unable to download {description} metadata',
            **kwargs,
        )
        if not isinstance(response, dict):
            raise ExtractorError(f'JSON object expected, got: {response!r}')
        error = response.get('error')
        if error:
            error_code = error.get('code')
            raise ExtractorError(
                f'{self.IE_NAME} returned error: {error_code}', expected=True)
        return response['result']

    def _extract_formats(self, m3u8_url, video_id):
        formats = self._extract_m3u8_formats(m3u8_url, video_id, 'mp4')
        self._sort_formats(formats)
        return formats

    def _extract_thumbnails(self, thumbnails_dict):
        if not thumbnails_dict:
            return None
        thumbnails = []
        for index, thumbnail_size in enumerate(self._THUMBNAIL_SIZES):
            thumbnail_url = thumbnails_dict.get(thumbnail_size)
            if not thumbnail_url:
                continue
            thumbnails.append({
                'url': thumbnail_url,
                'preference': index,
            })
        return thumbnails

    def _extract_og_title(self, url, item_id):
        return self._og_search_title(self._download_webpage(url, item_id))


class WASDTVBaseVideoExtractor(WASDTVBaseExtractor):

    def _get_container(self, url):
        """
        Download and extract the media container dict for the given URL.
        Return the container dict.
        """
        raise NotImplementedError

    def _get_media_url(self, media_meta):
        """
        Extract the m3u8 URL from the media_meta dict.
        Return a tuple (url: str, is_live: bool).
        """
        raise NotImplementedError

    def _real_extract(self, url):
        container = self._get_container(url)
        stream = container['media_container_streams'][0]
        media = stream['stream_media'][0]
        media_meta = media['media_meta']
        media_url, is_live = self._get_media_url(media_meta)
        video_id = media.get('media_id') or container.get('media_container_id')
        return {
            'id': str(video_id),
            'title': (
                container.get('media_container_name')
                or self._extract_og_title(url, video_id)
            ),
            'description': container.get('media_container_description'),
            'thumbnails': self._extract_thumbnails(
                media_meta.get('media_preview_images')),
            'timestamp': parse_iso8601(container.get('created_at')),
            'view_count': int_or_none(stream.get(
                'stream_current_viewers' if is_live
                else 'stream_total_viewers'
            )),
            'is_live': is_live,
            'formats': self._extract_formats(media_url, video_id),
        }


@plugin.register('stream')
class WASDTVStreamExtractor(WASDTVBaseVideoExtractor):

    DLP_REL_URL = r'(?:channel/(?P<channel_id>\d+)|(?P<nickname>[^/#?]+))/?$'

    def _get_container(self, url):
        channel_id, nickname = self.dlp_match(
            url).group('channel_id', 'nickname')
        if not channel_id:
            channel_id = self._fetch(
                'channels', 'nicknames', nickname,
                item_id=nickname,
                description='channel',
            )['channel_id']
        containers = self._fetch(
            'v2', 'media-containers',
            query={
                'channel_id': channel_id,
                'media_container_type': 'SINGLE',
                'media_container_status': 'RUNNING',
            },
            item_id=channel_id,
            description='running media containers',
        )
        if not containers:
            raise ExtractorError(f'{nickname} is offline', expected=True)
        return containers[0]

    def _get_media_url(self, media_meta):
        return media_meta['media_url'], True


@plugin.register('record')
class WASDTVRecordExtractor(WASDTVBaseVideoExtractor):

    DLP_REL_URL = r'[^/#?]+/videos\?record=(?P<id>\d+)$'

    def _get_container(self, url):
        container_id = self._match_id(url)
        return self._fetch(
            'v2', 'media-containers', container_id,
            item_id=container_id,
            description='media container',
        )

    def _get_media_url(self, media_meta):
        media_archive_url = media_meta.get('media_archive_url')
        if media_archive_url:
            return media_archive_url, False
        return media_meta['media_url'], True


@plugin.register('clip')
class WASDTVClipExtractor(WASDTVBaseExtractor):

    DLP_REL_URL = r'[^/#?]+/clips\?clip=(?P<id>\d+)$'

    def _real_extract(self, url):
        clip_id = self._match_id(url)
        clip = self._fetch(
            'v2', 'clips', clip_id,
            item_id=clip_id,
            description='clip',
        )
        clip_data = clip['clip_data']
        return {
            'id': str(clip_id),
            'title': (
                clip.get('clip_title')
                or self._extract_og_title(url, clip_id)
            ),
            'thumbnails': self._extract_thumbnails(clip_data.get('preview')),
            'timestamp': parse_iso8601(clip.get('created_at')),
            'view_count': int_or_none(clip.get('clip_views_count')),
            'formats': self._extract_formats(clip_data['url'], clip_id),
        }
