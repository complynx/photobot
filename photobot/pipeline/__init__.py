import PIL.Image as Image
import PIL.ImageEnhance as Enhance

def pipeline(source: Image.Image, frame: Image.Image) -> Image.Image:
    source = source.convert('RGBA')
    frame = frame.convert('RGBA')

    # Increase the contrast of the source image
    enhancer = Enhance.Contrast(source)
    source = enhancer.enhance(1.10)  # 10% increase in contrast

    composition = Image.new('RGBA', source.size)

    # Perform alpha compositing to combine the two images
    composition.alpha_composite(source)
    composition.alpha_composite(frame)

    return composition
