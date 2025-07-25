from telegram import Chat, User
import time
import os
import uuid
import PIL.Image as Image
from PIL import ImageOps
import math
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
import logging
import numpy as np
from .config import Config

logger = logging.getLogger(__name__)

DEADLINE_BASIC = 24*60*60 # 24 hours

real_frame_size = 1080

files_path = "photos"

frame_filename =  "static/frame.png"

final_frame_size = 1000
jpeg_quality = 90

tasks_by_uuid = dict()
tasks_by_user = dict()
tasks_by_chat = dict()

main_executor = None


class ModelNotFoundException(Exception):
    pass

def init_photo_tasker(cfg: Config):
    global main_executor, files_path
    main_executor = ThreadPoolExecutor(max_workers=cfg.photo.cpu_threads, thread_name_prefix="photo_tasker")

    files_path = cfg.photo.storage_path
    if not os.path.exists(files_path):
        os.makedirs(files_path)
    for file_name in os.listdir(files_path):
        file_path = os.path.join(files_path, file_name)
        if os.path.isfile(file_path):
            os.remove(file_path)
        elif os.path.isdir(file_path):
            os.rmdir(file_path)

def async_thread(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # if executor == MAIN:
        e = main_executor
        return asyncio.get_event_loop().run_in_executor(e, lambda: func(*args, **kwargs))
    return wrapper


def centered_crop_with_padding(img, x, y, size):
    # Calculate the center of the original image
    original_center_x = img.width / 2
    original_center_y = img.height / 2

    # Calculate the new center of the cropped image
    new_center_x = original_center_x + x
    new_center_y = original_center_y + y

    # Calculate the crop box (left, upper, right, lower)
    left = new_center_x - size / 2
    upper = new_center_y - size / 2
    right = left + size
    lower = upper + size

    # Pad the original image if necessary
    padding_left = max(-left, 0)
    padding_upper = max(-upper, 0)
    padding_right = max(right - img.width, 0)
    padding_lower = max(lower - img.height, 0)
    padding = (int(padding_left), int(padding_upper), int(padding_right), int(padding_lower))
    
    if any(side > 0 for side in padding):
        img = ImageOps.expand(img, padding, fill=(0,0,0,0)) # You can change the fill color if needed

    # Update crop box if padding was applied
    left += padding_left
    upper += padding_upper
    right += padding_left
    lower += padding_upper

    # Crop the image
    cropped_img = img.crop((int(left), int(upper), int(right), int(lower)))

    return cropped_img

def resize(img, scale_x, scale_y):
    return img.resize((int(scale_x * img.size[0]), int(scale_y * img.size[1])), resample=Image.LANCZOS)

def img_transform(img, a, b, c, d, e, f):
    scaling_x = math.sqrt(a * a + c * c)
    scaling_y = math.sqrt(b * b + d * d)

    rotation = math.atan2(b, a)

    img = resize(img, scaling_x, scaling_y)
    img = img.rotate(-rotation * 180 / math.pi, expand=True, fillcolor=(0,0,0,0))

    return centered_crop_with_padding(img, -e, -f, real_frame_size)


class PhotoTask(object):
    debug_code = None
    
    def __init__(self, chat: Chat, user: User) -> None:
        self.chat = chat
        self.user = user
        self.start_date = time.time()

        if self.chat.id in tasks_by_chat:
            tasks_by_chat[self.chat.id].delete()
        if self.user.id in tasks_by_user:
            tasks_by_user[self.user.id].delete()
        self.id = uuid.uuid4()
        while self.id in tasks_by_uuid:
            self.id = uuid.uuid4()
        
        self.file = None
        self.cropped_file = None
        self.final_file = None
        self.tg_update = None
        self.tg_context = None
        
        tasks_by_uuid[self.id] = self
        tasks_by_chat[self.chat.id] = self
        tasks_by_user[self.user.id] = self
            
    @async_thread
    def transform_avatar(self, a: float,b: float,c: float,d: float,e: float,f: float):
        file = self.file
        with Image.open(file) as img:
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            cropped_img = img_transform(img, a,b,c,d,e,f)

        fn = self.get_cropped_file(True)
        cropped_img.save(fn, 'PNG')
        self.cropped_file = fn
    
    @async_thread
    def resize_avatar(self):
        file = self.file
        with Image.open(file) as img:
            pw, ph = img.size
            left = right = top = bottom = 0
            if pw < ph:
                top = (ph-pw)//2
                bottom = top+pw
                right = pw
            else:
                left = (pw-ph)//2
                right = left + ph
                bottom = ph
            cropped_img = img.crop((left,top,right,bottom))
        resized_img = cropped_img.resize((real_frame_size, real_frame_size), resample=Image.LANCZOS)

        fn = self.get_cropped_file(True)
        resized_img.save(fn, 'PNG')
        self.cropped_file = fn
    
    @async_thread
    def finalize_avatar(self):
        source = Image.open(self.get_cropped_file())
        frame = Image.open(frame_filename)

        from .pipeline import pipeline

        composition = pipeline(source, frame)

        final = composition.resize(
            (final_frame_size, final_frame_size),
            resample=Image.LANCZOS
        ).convert('RGB')

        final_name = self.get_final_file(True)
        final.save(final_name, quality=jpeg_quality, optimize=True)
        self.final_file = final_name
    
    def get_file_size(self):
        file = self.file
        with Image.open(file) as img:
            return img.size
    
    def is_file_small(self):
        w,h = self.get_file_size()
        return w*h < real_frame_size*real_frame_size

    def get_cropped_file(self, generate=False):
        if self.cropped_file is None and generate and self.file is not None:
            base_name, _ = os.path.splitext(self.file)
            return base_name + "_cropped.png"
        return self.cropped_file

    def get_final_file(self, generate=False):
        if self.final_file is None and generate and self.file is not None:
            base_name, _ = os.path.splitext(self.file)
            return base_name + "_final.jpg"
        return self.final_file
    
    def remove_file(self):
        if self.file is not None:
            os.remove(self.file)
            self.file = None
        if self.cropped_file is not None:
            os.remove(self.cropped_file)
            self.cropped_file = None
        if self.final_file is not None:
            os.remove(self.final_file)
            self.final_file = None
    
    def add_file(self, file_name: str, ext: str):
        if self.file is not None:
            self.remove_file()
        if not os.path.exists(files_path):
            os.makedirs(files_path)
        new_name = os.path.join(files_path, f"{self.id.hex}.{ext}")
        os.rename(file_name, new_name)
        self.file = new_name
    
    def delete(self) -> None:
        del tasks_by_chat[self.chat.id]
        del tasks_by_user[self.user.id]
        del tasks_by_uuid[self.id]
        self.remove_file()

def get_by_uuid(id: uuid.UUID|str) -> PhotoTask:
    if not isinstance(id, uuid.UUID):
        id = uuid.UUID(id)
    return tasks_by_uuid[id]

def get_by_chat(id: int) -> PhotoTask:
    return tasks_by_chat[id]

def get_by_user(id: int) -> PhotoTask:
    return tasks_by_user[id]

