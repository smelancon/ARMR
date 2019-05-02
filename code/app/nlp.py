from pathlib import Path
import random
import spacy
from spacy.matcher import Matcher, PhraseMatcher
from spacy.util import minibatch, compounding

TERMINOLOGY = [
        "history of present illness", "past medical and surgical history",
        "past medical history", "review of systems", "family history",
        "social history", "medications prior to admission",
        "allergies", "physical examination", "electrocardiogram", "impression",
        "recommendations"]


def load_model(model_dir):
    """Takes a file path to model weights and returns a SpaCy model"""
    return spacy.load(model_dir)


def prepare_note(model, text):
    """Output of spaCy text processing containing categories, text, diseases,
        and medications"""
    note_sections = categorize_note(model, text)
    for section in note_sections:
        diseases, medications = parse_entities(model, note_sections[section][
            'text'])
        note_sections[section]['diseases'] = diseases
        note_sections[section]['medications'] = medications
    return note_sections


def categorize_note(model, text):
    """Breakup notes into different sections"""
    categories = {}
    matcher = PhraseMatcher(model.vocab)
    patterns = [model.make_doc(text) for text in TERMINOLOGY]
    matcher.add("Categories", None, *patterns)
    doc_lower = model(text.lower())
    doc = model(text)
    matches = matcher(doc_lower)
    results = []
    for match_id, start, end in matches:
        span = doc_lower[start:end]
        results.append((span, start, end))
    results = sorted(results, key=lambda tup: tup[1])
    for i in range(len(results)):
        result = results[i]
        next_result = results[i+1] if i < len(results)-1 else None
        category = str(result[0])
        start = result[2] if i != 0 else result[2]
        end = next_result[1] if next_result else None
        if end:
            categories[category] = {'text': doc[start:end].text}
        else:
            categories[category] = {'text': doc[start:].text}
    return categories


def parse_entities(model, text):
    """model identifies clinical text from transcribed text"""
    diseases = []
    medications = []
    matcher = Matcher(model.vocab)

    has_method_pattern = [
        {"ENT_TYPE": "CHEMICAL"},
        {"LIKE_NUM": True},
        {"LOWER": "mg"}, {}]
    matcher.add("HasMethod", None, has_method_pattern)

    no_method_pattern = [
        {"ENT_TYPE": "CHEMICAL"},
        {"LIKE_NUM": True},
        {"LOWER": "mg"}]
    matcher.add("NoMethod", None, no_method_pattern)

    just_drug_pattern = [{"ENT_TYPE": "CHEMICAL"}]
    matcher.add("JustDrug", None, just_drug_pattern)

    for entity in model(text).ents:
        if entity.label_ == 'DISEASE':
            diseases.append({'name': str(entity)})

    doc = model(text)
    matches = matcher(doc)
    if matches:
        last_start = None
        last_end = None
        for match_id, start, end in matches:
            string_id = model.vocab.strings[match_id]
            span = doc[start:end]
            if start != last_start and last_start is not None:
                medication = parse_medication(doc[last_start:last_end])
                if '.' not in medication['name']:
                    medications.append(medication)
            last_start = start
            last_end = end
        medication = parse_medication(doc[start:end])
        if '.' not in medication['name']:
            medications.append(parse_medication(doc[start:end]))
    return diseases, medications


def parse_medication(span):
    if len(span) == 4:
        method = None if span[-1].text == '.' else span[-1].text
        return {'name': span[0].text, 'amount': span[1].text,
                'unit': span[2].text, 'method': method}
    elif len(span) == 3:
        method = None if span[-1].text == '.' else span[-1].text
        return {'name': span[0].text, 'amount': span[1].text,
                'unit': span[2].text, 'method': method}
    else:
        return {'name': span[0].text, 'amount': None,
                'unit': None, 'method': None}


def train(model, train_data, output_dir, n_iter=100):
    if model is not None:
        nlp = spacy.load(model)  # load existing spaCy model
        print("Loaded model '%s'" % model)
    else:
        nlp = spacy.blank("en")  # create blank Language class
        print("Created blank 'en' model")

    # for text, _ in train_data:
    #     doc = nlp(text)
    #     print("Entities", [(ent.text, ent.label_) for ent in doc.ents])

    # create the built-in pipeline components and add them to the pipeline
    # nlp.create_pipe works for built-ins that are registered with spaCy
    if "ner" not in nlp.pipe_names:
        ner = nlp.create_pipe("ner")
        nlp.add_pipe(ner, last=True)
    # otherwise, get it so we can add labels
    else:
        ner = nlp.get_pipe("ner")

    # add labels
    for _, annotations in train_data:
        for ent in annotations.get("entities"):
            ner.add_label(ent[2])

    # get names of other pipes to disable them during training
    other_pipes = [pipe for pipe in nlp.pipe_names if pipe != "ner"]
    with nlp.disable_pipes(*other_pipes):  # only train NER
        # reset and initialize the weights randomly – but only if we're
        # training a new model
        if model is None:
            nlp.begin_training()
        for itn in range(n_iter):
            random.shuffle(train_data)
            losses = {}
            # batch up the examples using spaCy's minibatch
            batches = minibatch(train_data, size=compounding(4.0, 32.0, 1.001))
            for batch in batches:
                texts, annotations = zip(*batch)
                nlp.update(
                    texts,  # batch of texts
                    annotations,  # batch of annotations
                    drop=0.5,  # dropout - make it harder to memorise data
                    losses=losses,
                )
            print("Losses", losses)

    for text, _ in train_data[0:5]:
        doc = nlp(text)
        print("Entities", [(ent.text, ent.label_) for ent in doc.ents])

    # if output_dir is not None:
    #     output_dir = Path(output_dir)
    #     if not output_dir.exists():
    #         output_dir.mkdir()
    #     nlp.to_disk(output_dir)
    #     print("Saved model to ", output_dir)


    # return nlp
    # """Named Entity Recognition Training loop"""
    # test_string = "the patient is a 52 year old female and has a previous history of aortic valve disease and a status " \
    #               "post aortic valve replacement on october 15th 2007 for when she has been on chronic anticoagulation."
    # doc = model(test_string)
    # for ent in doc.ents:
    #     print((ent.text, ent.label_))
    #
    # other_pipes = [pipe for pipe in model.pipe_names if pipe != "ner"]
    #
    # with model.disable_pipes(*other_pipes):
    #     for itn in range(n_iter):
    #         random.shuffle(train_data)
    #         losses = {}
    #         batches = minibatch(train_data, size=compounding(4.0, 32.0, 1.001))
    #         for batch in batches:
    #             texts, annotations = zip(*batch)
    #             model.update(
    #                 texts,
    #                 annotations,
    #                 drop=0.5,
    #                 losses=losses,
    #             )
    #         print("Losses", losses)
    #
    #
    # doc = model(test_string)
    # for ent in doc.ents:
    #     print((ent.text, ent.label_))
    # return model
    # if output_dir is not None:
    #     output_dir = Path(output_dir)
    #     if not output_dir.exists():
    #         output_dir.mkdir()
    #     model.to_disk(output_dir)
    #     print("Saved model to ", output_dir)
