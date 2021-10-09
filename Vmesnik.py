from bottle import *
from Model_Partija import Partija
from Model_Igralec import Igralec

partija = None

####FIX Č Ž Š !!!!!!!!!!! SERVER CRASHA

@route('/')
def vnos_igralcev():
    #later partija = None
    return template('form.tpl')

@post('/razpredelnica') # or @route('/login', method='POST')
##js mislim da ta funkcija lahko pohendla dva casa, ki sta / -> /razpredelnica in pa /razpredelnica -> /razpredelnica oziroma "submit"
def seznam_igralcev():
    ##to naredi z nule nove igralce in jih da v partijo... ampak mi bi rabili nacin da samo dodamo podatke v obstojeco partijo in gremo na new page
    
    global partija
    if partija == None:
        ##partije ni, naredimo novo
        igralci = []
        for i in range(5):
            igralec = request.forms.getunicode('igralec' + str(i+1))
            if not igralec == "":
                igralci.append(Igralec(igralec))
        partija = Partija(igralci)        
        
    else:
        ##posodobi podatke v partiji
        ime_igralec = request.forms.getunicode('igralec')
        if not ime_igralec == None:
            igra = request.forms.get('igre')
            razlika = request.forms.get('razlika')
            dodatne = request.forms.get('dodatne')
            zmaga = True if request.forms.get('zmaga') == 'zmaga' else False
            ime_soigralec = request.forms.getunicode('soigralec')            
            partija.igraj(ime_igralec, igra, razlika, dodatne, zmaga, ime_soigralec)
            ##če pa ime je None, pa imamo že eno partijo in progress + dostopamo spet z začetne strani... pa dajmo prikazat obstoječo partijo in progress

    return template('razpredelnica.tpl', partija=partija)
        

run(host='localhost', port=8080)