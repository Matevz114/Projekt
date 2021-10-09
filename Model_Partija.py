from Model_Igralec import Igralec

class Partija:
    def __init__(self, seznam_igralcev):
        self.seznam_igralcev = seznam_igralcev
        imena = []
        for igralec in seznam_igralcev:
            imena.append(igralec.ime)
        self.seznam_igralcev_imena = imena


class Partija(Partija):


    def stevilo_igralcev(self):
        return len(self.seznam_igralcev)

    def ime_igralca(self, index_igralca):
        return self.seznam_igralcev[index_igralca].ime

    def stevilo_tock_igralca(self, index_igralca):
        return self.seznam_igralcev[index_igralca].tocke

    def stevilo_radelcev_igralca(self, index_igralca):
        return self.seznam_igralcev[index_igralca].radelci

    def get_igralec(self, ime_igralec):
        for igralec in self.seznam_igralcev:
            if igralec.ime == ime_igralec:
                return igralec
            ##dejmo rect da imajo igralci po logiki razlicna imena/vzdevke

    def klop(self):
        for igralec in self.seznam_igralcev:
            igralec.dodaj_radelc()
        return

    def igraj(self, ime_igralec, igra, razlika, dodatne, zmaga, ime_soigralec):
        ##tle bo sanitation of input
        ##razlika in dodatne spremenit v stevilo
        #klopception:
        print("igramo igro ", igra)
        if igra == "klop":
            return self.klop()
        
        
        if dodatne.replace('-','').isnumeric():
            dodatne = int(dodatne)
        else:
            dodatne = 0

        #rocniception:
        if igra == "rocno":
            print("Igra je rocna")
            return self.get_igralec(ime_igralec).dodaj_tocke(dodatne)


        if razlika.replace('-','').isnumeric():
            razlika = int(razlika.replace('-',''))
        else:
            razlika = 0          
        

        igralec = self.get_igralec(ime_igralec)  ##to je retrieved as NONE
        soigralec = self.get_igralec(ime_soigralec)
        solos = ["solo tri", "solo dva", "solo ena", "berac", "solo brez", "valat"]
        if igra in solos:
            soigralec = None
        brezrazlike = ["berac", "valat"]
        if igra in brezrazlike:
            razlika = 0
        igralec.igra_s_parametri(igra, razlika, dodatne, zmaga, soigralec)
        return



    