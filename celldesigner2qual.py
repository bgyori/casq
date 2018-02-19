#!/usr/bin/env python3
'''
Convert CellDesigner models to SBML-qual with a rather strict semantics
'''
import sys
from itertools import chain, repeat
import xml.etree.ElementTree as etree
import collections


NS = {
    'sbml': 'http://www.sbml.org/sbml/level2/version4',
    'cd': 'http://www.sbml.org/2001/ns/celldesigner',
    'sbml3': 'http://www.sbml.org/sbml/level3/version1/core',
    'layout': 'http://www.sbml.org/sbml/level3/version1/layout/version1',
    'qual': 'http://www.sbml.org/sbml/level3/version1/qual/version1',
    'mathml': 'http://www.w3.org/1998/Math/MathML',
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'dcterms': 'http://purl.org/dc/terms/',
    'vCard': 'http://www.w3.org/2001/vcard-rdf/3.0#',
    'bqbiol': 'http://biomodels.net/biology-qualifiers/',
    'bqmodel': 'http://biomodels.net/model-qualifiers/',
    'xhtml': 'http://www.w3.org/1999/xhtml'
}

GINSIM = False


Transition = collections.namedtuple('Transition', [
    'type', 'reactants', 'modifiers', 'notes', 'annotations'])


def read_celldesigner(filename):
    '''main file parsing function'''
    root = etree.parse(filename).getroot()
    tag = root.tag
    if tag != f'{{{NS["sbml"]}}}sbml':
        print('Currently limited to SBML Level 2 Version 4')
        exit(1)
    model = root.find('sbml:model', NS)
    return get_transitions(model, species_info(model))


def species_info(model):
    '''create a map from species' ids to their attributes'''
    nameconv = {}
    for species in chain(
            model.findall(
                './sbml:annotation/cd:extension/' +
                'cd:listOfComplexSpeciesAliases/' +
                'cd:complexSpeciesAlias[@compartmentAlias]', NS),
            model.findall(
                './sbml:annotation/cd:extension/' +
                'cd:listOfSpeciesAliases/' +
                'cd:speciesAlias[@compartmentAlias]', NS),
    ):
        activity = species.find('.//cd:activity', NS).text
        bound = species.find('.//cd:bounds', NS)
        sbml = model.find('./sbml:listOfSpecies/sbml:species[@id="' +
                          species.get('species') + '"]', NS)
        annot = sbml.find('./sbml:annotation', NS)
        cls = get_class(annot.find('.//cd:class', NS))
        mods = get_mods(annot.find('.//cd:listOfModifications', NS))
        rdf = annot.find('.//rdf:RDF', NS)
        nameconv[species.get('id')] = {
            'activity': activity,
            'x': bound.get('x'),
            'y': bound.get('y'),
            'h': bound.get('h'),
            'w': bound.get('w'),
            'transitions': [],
            'name': sbml.get('name'),
            'type': cls,
            'modifications': mods,
            'annotations': rdf,
        }
    return nameconv


def get_transitions(model, info):
    '''find all transitions'''
    for trans in model.findall('./sbml:listOfReactions/sbml:reaction', NS):
        annot = trans.find('./sbml:annotation/cd:extension', NS)
        rtype = annot.find('./cd:reactionType', NS).text
        reacs = [decomplexify(reac.get('alias'), model) for reac in
                 annot.findall('./cd:baseReactants/cd:baseReactant', NS)]
        prods = [decomplexify(prod.get('alias'), model) for prod in
                 annot.findall('./cd:baseProducts/cd:baseProduct', NS)]
        mods = [(mod.get('type'),
                 decomplexify(mod.get('aliases'), model)) for mod in
                annot.findall('./cd:listOfModification/cd:modification', NS)]
        notes = trans.find('./sbml:notes//xhtml:body', NS)
        rdf = trans.find('./sbml:annotation/rdf:RDF', NS)
        for species in prods:
            if species in info:
                info[species]['transitions'].append(
                    Transition(rtype, reacs, mods, notes, rdf)
                )
            else:
                print(f'ignoring unknown species {species}')
    return info


def decomplexify(species, model):
    '''return external complex if there is one, or species unchanged
    otherwise'''
    cmplx = model.find('./sbml:annotation/cd:extension/' +
                       'cd:listOfSpeciesAliases/' +
                       'cd:speciesAlias[@id="' + species + '"]', NS)
    if cmplx is None:
        return species
    return cmplx.get('complexSpeciesAlias', species)


def get_class(cd_class):
    '''celldesigner:class to class'''
    if cd_class is not None:
        return cd_class.text
    return 'PROTEIN'


def get_mods(cd_modifications):
    '''celldesigner:listOfModifications to list of mods'''
    mods = []
    if cd_modifications:
        for mod in cd_modifications.findall('cd:modification', NS):
            mods.append(mod.get('state'))
    return mods


def write_qual(filename, info):
    '''write the SBML qual with layout file for our model'''
    for name, space in NS.items():
        etree.register_namespace(name, space)
    root = etree.Element('sbml', {
        'level': '3', 'version': '1', 'layout:required': 'false',
        'xmlns': NS['sbml3'], 'qual:required': 'true',
        'xmlns:layout': NS['layout'], 'xmlns:qual': NS['qual'],
    })
    model = etree.Element('model', id="model_id")
    clist = etree.SubElement(model, 'listOfCompartments')
    etree.SubElement(clist, 'compartment', constant="true", id="comp1")
    llist = etree.SubElement(model, 'layout:listOfLayouts')
    layout = etree.SubElement(llist, 'layout:layout')
    qlist = etree.SubElement(model, 'qual:listOfQualitativeSpecies')
    add_positions(layout, qlist, info)
    tlist = etree.SubElement(model, 'qual:listOfTransitions')
    add_transitions(tlist, info)
    root.append(model)
    tree = etree.ElementTree(root)
    tree.write(filename, "UTF-8", xml_declaration=True)


def add_positions(layout, qlist, info):
    '''create layout sub-elements'''
    llist = etree.SubElement(layout, 'layout:listOfSpeciesGlyphs')
    for species, data in info.items():
        glyph = etree.SubElement(
            llist, 'layout:speciesGlyph',
            {'layout:species': species})
        box = etree.SubElement(glyph, 'layout:boundingBox')
        etree.SubElement(
            box, 'layout:position',
            {'layout:x': data['x'], 'layout:y': data['y']})
        etree.SubElement(
            box, 'layout:dimensions',
            {'layout:height': data['h'], 'layout:width': data['w']})
        if data['transitions']:
            constant = "false"
        else:
            constant = "true"
        qspecies = etree.SubElement(
            qlist,
            'qual:qualitativeSpecies',
            {
                'qual:maxLevel': "1",
                'qual:compartment': "comp1",
                'qual:name': data['name'],
                'qual:constant': constant,
                'qual:id': species,
            })
        if GINSIM:
            # ginsim bug uses name as id
            qspecies.set(
                'qual:name',
                data['name'].replace(' ', '_').replace(',', '').replace(
                    '/', '_') + '_' + species
            )
        add_annotation(qspecies, data['annotations'])


def add_annotation(node, rdf):
    '''add a single RDF element as an annotation node'''
    if rdf is not None:
        etree.SubElement(
            node,
            'annotation'
        ).append(rdf)


def add_transitions(tlist, info):
    '''create transition elements'''
    for species, data in info.items():
        if data['transitions']:
            trans = etree.SubElement(tlist, 'qual:transition', {
                'qual:id': f'tr_{species}'
            })
            ilist = etree.SubElement(trans, 'qual:listOfInputs')
            add_inputs(ilist, data['transitions'], species)
            olist = etree.SubElement(trans, 'qual:listOfOutputs')
            etree.SubElement(olist, 'qual:output', {
                'qual:qualitativeSpecies': species,
                'qual:transitionEffect': 'assignmentLevel',
                'qual:id': f'tr_{species}_out'
            })
            flist = etree.SubElement(trans, 'qual:listOfFunctionTerms')
            etree.SubElement(flist, 'qual:defaultTerm', {
                'qual:resultLevel': '0'
            })
            func = etree.SubElement(flist, 'qual:functionTerm', {
                'qual:resultLevel': '1'
            })
            add_function(func, data['transitions'])
            add_notes(trans, data['transitions'])
            add_annotations(trans, data['transitions'])


def add_notes(trans, transitions):
    '''add all the found notes'''
    notes = etree.SubElement(trans, 'notes')
    html = etree.SubElement(notes, 'html', xmlns=NS['xhtml'])
    head = etree.SubElement(html, 'head')
    etree.SubElement(head, 'title')
    body = etree.SubElement(html, 'body')
    some_notes = False
    prefix_len = len(NS['xhtml']) + 2
    for reaction in transitions:
        if reaction.notes is not None:
            some_notes = True
            reaction.notes.tag = 'p'
            for element in reaction.notes.getiterator():
                if element.tag.startswith(f"{{{NS['xhtml']}}}"):
                    element.tag = element.tag[prefix_len:]
            body.append(reaction.notes)
    if not some_notes:
        trans.remove(notes)


def add_annotations(trans, transitions):
    '''add all the found annotations'''
    annotation = etree.SubElement(trans, 'annotation')
    rdf = etree.SubElement(annotation, 'rdf:RDF')
    for reaction in transitions:
        if reaction.annotations is not None:
            rdf.append(reaction.annotations[0])
    if not rdf:
        trans.remove(annotation)


def add_function(func, transitions):
    '''add the complete boolean function'''
    math = etree.SubElement(func, 'math', xmlns=NS['mathml'])
    # create or node if necessary
    if len(transitions) > 1:
        apply = etree.SubElement(math, 'apply')
        etree.SubElement(apply, 'or')
    else:
        apply = math
    for reaction in transitions:
        reactants = reaction.reactants
        activators = [mod for (modtype, modifier) in reaction.modifiers
                      for mod in modifier.split(',') if
                      modtype != 'INHIBITION']
        inhibitors = [mod for (modtype, modifier) in reaction.modifiers
                      for mod in modifier.split(',') if
                      modtype == 'INHIBITION']
        # create and node if necessary
        if len(reactants) + len(inhibitors) > 1 or (
                activators and (reactants or inhibitors)):
            lapply = etree.SubElement(apply, 'apply')
            etree.SubElement(lapply, 'and')
        else:
            lapply = apply
        if len(activators) < 2:
            reactants.extend(activators)
        else:
            # create or node if necessary
            inner_apply = etree.SubElement(lapply, 'apply')
            etree.SubElement(inner_apply, 'or')
            for modifier in activators:
                set_level(inner_apply, modifier, '1')
        for level, modifier in chain(zip(repeat('1'), reactants),
                                     zip(repeat('0'), inhibitors)):
            set_level(lapply, modifier, level)


def set_level(elt, modifier, level):
    '''add mathml to element elt such that modifier is equal to level'''
    trigger = etree.SubElement(elt, 'apply')
    etree.SubElement(trigger, 'eq')
    math_ci = etree.SubElement(trigger, 'ci')
    math_ci.text = modifier
    math_cn = etree.SubElement(trigger, 'cn', type='integer')
    math_cn.text = level


def add_inputs(ilist, transitions, species):
    '''add all known inputs'''
    index = 0
    modifiers = []
    for reaction in transitions:
        # we use enumerate to get a dummy modtype for reactants
        for modtype, modifier in chain(enumerate(reaction.reactants),
                                       reaction.modifiers):
            if modtype == 'INHIBITION':
                sign = 'negative'
            else:
                sign = 'positive'
            if (modifier, sign) not in modifiers:
                modifiers.append((modifier, sign))
                etree.SubElement(ilist, 'qual:input', {
                    'qual:qualitativeSpecies': modifier,
                    'qual:transitionEffect': 'none',
                    'qual:sign': sign,
                    'qual:id': f'tr_{species}_in_{index}',
                })
                index += 1


def main():
    '''run conversion using the CLI given first argument'''
    if len(sys.argv) > 1 and sys.argv[1] == '--ginsim':
        global GINSIM   # pylint: disable=global-statement
        GINSIM = True
    if len(sys.argv) != 3:
        print(f'Usage: [python3] {sys.argv[0]} ' +
              '<celldesignerinfile.xml> <sbmlqualoutfile.xml>')
        exit(1)
    celldesignerfile = sys.argv[1]
    print(f'parsing {celldesignerfile}…')
    info = read_celldesigner(celldesignerfile)
    write_qual(sys.argv[2], info)


if __name__ == '__main__':  # pragma: no cover
    main()
