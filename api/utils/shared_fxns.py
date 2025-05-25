from datetime import datetime

def find_date_difference(start_date,end_date,period):
    try:
        start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date, '%Y-%m-%d').date()

        # Calculate the difference

        if period == 'days':
            difference = end_date - start_date
            difference = difference.days
        elif period == 'weeks':
            difference = (end_date - start_date).days // 7
        elif period == 'months':
            difference = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
        elif period == 'years':
            difference = end_date.year - start_date.year

        # return difference
        return difference
        
    except Exception as e:
        print(e)
        return 'error'


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