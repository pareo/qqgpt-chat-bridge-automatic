"""Build a downloadable looping GIF from a generated 3×3 frame sheet."""

import io

from PIL import Image, ImageOps

from .media import ImageError


FRAME_GRID = 3
FRAME_SIZE = (300, 300)
FRAME_MS = 170
MAX_GIF_BYTES = 10 * 1024 * 1024
MAX_FRAME_PIXELS = 40_000_000
MAX_ANIMATION_PIXELS = 48_000_000


def animation_prompt(prompt: str) -> str:
    return (
        '使用实际生图工具，返回一张正方形 PNG 动画分镜图。不要使用远程文件、代码或文字链接交付 GIF，'
        '发送端会把分镜图切成动画。图片必须填满画布，精确分成 3 列 × 3 行的 9 个等大格子，'
        '按从左至右、从上至下排列。无边框、间隙、编号和水印，各格使用一致的背景、取景、主体位置和尺寸。'
        '动作在连续格子间逐步变化，最后一格自然循环接回第一格。用户原始动作和主题如下：\n' + prompt
    )


def looping_gif(raw: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(raw)) as picture:
            width, height = picture.size
            if width * height > MAX_FRAME_PIXELS:
                raise ImageError('动画分镜图像素超过上限')
            if picture.format == 'GIF' and picture.is_animated:
                count = picture.n_frames
                if len(raw) > MAX_GIF_BYTES or count > 120 or width * height * count > MAX_ANIMATION_PIXELS:
                    raise ImageError('GIF 动图超过大小或帧数上限')
                for index in range(count):
                    picture.seek(index)
                    picture.load()
                return raw
            if getattr(picture, 'is_animated', False):
                raise ImageError('请返回 GIF 动图或静态分镜图')
            if min(width, height) < 300 or not 0.9 <= width / height <= 1.1:
                raise ImageError('未取得尺寸合适的正方形动画分镜图')
            frames = []
            for row in range(FRAME_GRID):
                for column in range(FRAME_GRID):
                    bounds = (column * width // FRAME_GRID, row * height // FRAME_GRID,
                              (column + 1) * width // FRAME_GRID, (row + 1) * height // FRAME_GRID)
                    frame = picture.crop(bounds).convert('RGBA')
                    background = Image.new('RGBA', frame.size, 'white')
                    background.alpha_composite(frame)
                    frames.append(ImageOps.fit(background.convert('RGB'), FRAME_SIZE, Image.Resampling.LANCZOS))
            if all(frame.tobytes() == frames[0].tobytes() for frame in frames[1:]):
                raise ImageError('动画分镜没有不同的画面')
            result = io.BytesIO()
            frames[0].save(result, format='GIF', save_all=True, append_images=frames[1:],
                           duration=FRAME_MS, loop=0, disposal=2, optimize=True)
            if result.tell() > MAX_GIF_BYTES:
                raise ImageError('GIF 动图超过 10 MiB')
            payload = result.getvalue()
            with Image.open(io.BytesIO(payload)) as generated:
                if not generated.is_animated:
                    raise ImageError('动图转换只得到了一帧')
            return payload
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImageError('动画分镜图损坏或无法转换') from exc
