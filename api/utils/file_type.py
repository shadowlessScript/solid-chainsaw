
def identify_file_type(ext):
    images = ['jpeg', 'jpg', 'png', 'tiff']
    videos = ['mp4','webm', 'mkv']
    files = ['pdf']

    if ext.lower() in images:
        return 'IMAGE'
    elif ext.lower() in videos:
        return 'VIDEO'
    elif ext.lower() in files:
        return 'FILE'
    else:
        return 'UNKNOWN'