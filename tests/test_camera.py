from unittest.mock import Mock, patch

import pytest

from desktop_agent.tools.camera import PHOTO_MODE, PHOTO_SHUTTER, CameraTools


def button(name, visible=True, enabled=True):
    item = Mock()
    item.window_text.return_value = name
    item.is_visible.return_value = visible
    item.is_enabled.return_value = enabled
    return item


@pytest.mark.parametrize(
    "name",
    ["切换到 照片 模式", "切换到照片模式", "切换到\u00a0照片\u00a0模式", "Switch to photo mode"],
)
def test_actual_camera_mode_labels(name):
    assert PHOTO_MODE.fullmatch(name)


@pytest.mark.parametrize(
    "name", ["录制视频", "拍摄视频", "Record video", "本机照片", "CaptureButton_1"]
)
def test_never_mistake_video_or_gallery_for_photo_shutter(name):
    assert not PHOTO_SHUTTER.fullmatch(name)
    assert not PHOTO_MODE.fullmatch(name)


def test_switch_video_mode_then_return_photo_shutter_without_capturing():
    camera = CameraTools()
    window = Mock()
    mode, video, photo = button("切换到 照片 模式"), button("录制视频"), button("拍照")
    current = [mode, video]
    window.descendants.side_effect = lambda **kwargs: current
    mode.invoke.side_effect = lambda: current.__setitem__(slice(None), [photo])
    with patch("desktop_agent.tools.camera.time.sleep"):
        shutter = camera._shutter(window)
    assert shutter is photo
    mode.invoke.assert_called_once()
    video.invoke.assert_not_called()
    photo.invoke.assert_not_called()


def test_already_in_photo_mode_does_not_press_mode_or_shutter():
    camera = CameraTools()
    window, photo = Mock(), button("拍照")
    window.descendants.return_value = [photo]
    assert camera._shutter(window) is photo
    photo.invoke.assert_not_called()


def test_missing_shutter_reports_actual_names():
    window = Mock()
    window.descendants.return_value = [button("录制视频"), button("本机照片")]
    with pytest.raises(RuntimeError, match="当前可用按钮"):
        CameraTools()._shutter(window)


def test_open_never_captures():
    camera, window = CameraTools(), Mock()
    window.is_minimized.return_value = False
    with (
        patch.object(camera, "_find", return_value=window),
        patch.object(camera, "_shutter") as shutter,
    ):
        camera.open()
    shutter.assert_not_called()
    window.set_focus.assert_called_once()


def test_photo_requires_open_camera():
    camera = CameraTools()
    with patch.object(camera, "_find", return_value=None):
        with pytest.raises(RuntimeError, match="请先说"):
            camera.take_photo()


def test_photo_invokes_once_and_waits_for_new_photo(tmp_path):
    camera, window, shutter = CameraTools(tmp_path), Mock(), Mock()
    photo = tmp_path / "photo.jpg"
    shutter.invoke.side_effect = lambda: photo.write_bytes(b"test")
    window.is_minimized.return_value = False
    with (
        patch.object(camera, "_find", return_value=window),
        patch.object(camera, "_shutter", return_value=shutter),
        patch("desktop_agent.tools.camera.time.sleep"),
    ):
        result = camera.take_photo()
    shutter.invoke.assert_called_once()
    assert str(photo) in result
