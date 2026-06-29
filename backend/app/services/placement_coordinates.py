from __future__ import annotations

from typing import Any

import fitz


def normalized_rect(rect: list[float] | tuple[float, float, float, float]) -> list[float]:
    values = [float(value) for value in rect[:4]]
    x0, x1 = sorted([values[0], values[2]])
    y0, y1 = sorted([values[1], values[3]])
    return round_rect([x0, y0, x1, y1])


def round_rect(rect: list[float] | tuple[float, float, float, float], digits: int = 2) -> list[float]:
    return [round(float(value), digits) for value in rect[:4]]


def page_geometry(page: fitz.Page) -> dict[str, float | int]:
    return {
        "source_width": float(page.cropbox.width),
        "source_height": float(page.cropbox.height),
        "display_width": float(page.rect.width),
        "display_height": float(page.rect.height),
        "page_rotation": int(page.rotation or 0) % 360,
    }


def image_rect_to_pdf_rect(
    image_rect: list[float],
    *,
    image_width: float,
    image_height: float,
    source_width: float,
    source_height: float,
    display_width: float,
    display_height: float,
    rotation: int,
) -> list[float]:
    display_rect = image_rect_to_display_rect(
        image_rect,
        image_width=image_width,
        image_height=image_height,
        display_width=display_width,
        display_height=display_height,
    )
    return display_rect_to_pdf_rect(
        display_rect,
        source_width=source_width,
        source_height=source_height,
        rotation=rotation,
    )


def pdf_rect_to_image_rect(
    pdf_rect: list[float],
    *,
    image_width: float,
    image_height: float,
    source_width: float,
    source_height: float,
    display_width: float,
    display_height: float,
    rotation: int,
) -> list[float]:
    display_rect = pdf_rect_to_display_rect(
        pdf_rect,
        source_width=source_width,
        source_height=source_height,
        rotation=rotation,
    )
    return display_rect_to_image_rect(
        display_rect,
        image_width=image_width,
        image_height=image_height,
        display_width=display_width,
        display_height=display_height,
    )


def image_rect_to_display_rect(
    image_rect: list[float],
    *,
    image_width: float,
    image_height: float,
    display_width: float,
    display_height: float,
) -> list[float]:
    rect = normalized_rect(image_rect)
    if image_width <= 0 or image_height <= 0 or display_width <= 0 or display_height <= 0:
        return rect
    scale_x = display_width / image_width
    scale_y = display_height / image_height
    return round_rect([rect[0] * scale_x, rect[1] * scale_y, rect[2] * scale_x, rect[3] * scale_y])


def display_rect_to_image_rect(
    display_rect: list[float],
    *,
    image_width: float,
    image_height: float,
    display_width: float,
    display_height: float,
) -> list[float]:
    rect = normalized_rect(display_rect)
    if image_width <= 0 or image_height <= 0 or display_width <= 0 or display_height <= 0:
        return rect
    scale_x = image_width / display_width
    scale_y = image_height / display_height
    return round_rect([rect[0] * scale_x, rect[1] * scale_y, rect[2] * scale_x, rect[3] * scale_y])


def display_rect_to_pdf_rect(
    display_rect: list[float],
    *,
    source_width: float,
    source_height: float,
    rotation: int,
) -> list[float]:
    rect = normalized_rect(display_rect)
    if source_width <= 0 or source_height <= 0:
        return rect
    rotation = int(rotation or 0) % 360
    x0, y0, x1, y1 = rect
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def inverse_transform(x: float, y: float) -> tuple[float, float]:
        if rotation == 90:
            return y, source_height - x
        if rotation == 180:
            return source_width - x, source_height - y
        if rotation == 270:
            return source_width - y, x
        return x, y

    transformed = [inverse_transform(x, y) for x, y in corners]
    xs = [point[0] for point in transformed]
    ys = [point[1] for point in transformed]
    return round_rect(
        [
            max(0.0, min(xs)),
            max(0.0, min(ys)),
            min(source_width, max(xs)),
            min(source_height, max(ys)),
        ]
    )


def pdf_rect_to_display_rect(
    pdf_rect: list[float],
    *,
    source_width: float,
    source_height: float,
    rotation: int,
) -> list[float]:
    rect = normalized_rect(pdf_rect)
    if source_width <= 0 or source_height <= 0:
        return rect
    rotation = int(rotation or 0) % 360
    x0, y0, x1, y1 = rect
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    def transform(x: float, y: float) -> tuple[float, float]:
        if rotation == 90:
            return source_height - y, x
        if rotation == 180:
            return source_width - x, source_height - y
        if rotation == 270:
            return y, source_width - x
        return x, y

    transformed = [transform(x, y) for x, y in corners]
    xs = [point[0] for point in transformed]
    ys = [point[1] for point in transformed]
    return round_rect([min(xs), min(ys), max(xs), max(ys)])


def geometry_from_page_and_image(page: fitz.Page, image_width: float, image_height: float) -> dict[str, Any]:
    geometry = page_geometry(page)
    geometry["image_width"] = float(image_width)
    geometry["image_height"] = float(image_height)
    return geometry
