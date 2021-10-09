from bottle import *
from Model_Partija import Partija
from Model_Igralec import Igralec

partija = None


@route('/')
def vnos_igralcev():
    #later partija = None
    return template('form.tpl')

@post('/razpredelnica')
def seznam_igralcev():
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