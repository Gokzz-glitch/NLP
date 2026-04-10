import torch
import traceback

def main():
    try:
        logging.basicConfig(filename='logs/vision_slaughter.log', level=logging.INFO,
                            format='%(asctime)s %(levelname)s %(message)s')
        model = load_yolo_model()
        data = load_validation_set()
        y_true, y_pred = [], []
        for img, label in data:
            aug_img = brutal_augment(img)
            # Simulate model prediction
            with torch.no_grad():
                input_tensor = torch.from_numpy(aug_img.transpose(2, 0, 1)).unsqueeze(0).float().cuda()
                output = model(input_tensor)
                pred = output.argmax(dim=1).item()
            y_true.append(label)
            y_pred.append(pred)
            # Hallucination check: speed_breaker as pothole, speed_camera missed
            if label == 1 and pred == 2:
                logging.error('Hallucination: speed_breaker→pothole under low light')
            if label == 5 and pred != 5:
                logging.error('Missed speed_camera due to blur')
        cm = confusion_matrix(y_true, y_pred, labels=list(range(7)))
        recalls = cm.diagonal() / cm.sum(axis=1)
        for idx, recall in enumerate(recalls):
            if recall < 0.6:
                logging.critical(f'CRITICAL FAILURE: Recall for class {idx} below 60% ({recall:.2f})')
        logging.info(f'Confusion matrix:\n{cm}')
        print('Confusion matrix:')
        print(cm)
        print('Per-class recall:')
        print(recalls)
    except Exception as e:
        logging.error(f'Exception occurred: {e}')
        traceback.print_exc()
        with open("logs/vision_slaughter.log", "a") as f:
            f.write(traceback.format_exc())

if __name__ == '__main__':
    main()
    logging.basicConfig(filename='logs/vision_slaughter.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    model = load_yolo_model()
    data = load_validation_set()
    y_true, y_pred = [], []
    for img, label in data:
        aug_img = brutal_augment(img)
        # Simulate model prediction
        with torch.no_grad():
            input_tensor = torch.from_numpy(aug_img.transpose(2, 0, 1)).unsqueeze(0).float().cuda()
            output = model(input_tensor)
            pred = output.argmax(dim=1).item()
        y_true.append(label)
        y_pred.append(pred)
        # Hallucination check: speed_breaker as pothole, speed_camera missed
        if label == 1 and pred == 2:
            logging.error('Hallucination: speed_breaker→pothole under low light')
        if label == 5 and pred != 5:
            logging.error('Missed speed_camera due to blur')
    cm = confusion_matrix(y_true, y_pred, labels=list(range(7)))
    recalls = cm.diagonal() / cm.sum(axis=1)
    for idx, recall in enumerate(recalls):
        if recall < 0.6:
            logging.critical(f'CRITICAL FAILURE: Recall for class {idx} below 60% ({recall:.2f})')
    logging.info(f'Confusion matrix:\n{cm}')
    print('Confusion matrix:')
    print(cm)
    print('Per-class recall:')
    print(recalls)

if __name__ == '__main__':
    main()
