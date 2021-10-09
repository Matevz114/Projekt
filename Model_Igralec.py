import random

class Igralec:
    
    def __init__(self, ime):
        self.ime = ime
        self.tocke = [0]
        self.radelci = 0

class Igralec(Igralec):
    def dodaj_tocke(self, tocke):
        self.tocke.append(self.tocke[-1] + tocke)
        if len(self.tocke) > 20:
            popped = self.tocke.pop(0)
            print("popali smo ", popped)
            #ce zelimo seveda
        return self.tocke

    def dodaj_radelc(self):
        self.radelci += 1
        return self.radelci

    def izbrisi_radelc(self):
        self.radelci -= 1
        return self.radelci

    def trenutne_tocke(self):
        return self.tocke[-1]


    def igra_s_parametri(self, igra1, razlika1=0,dodatne_tocke=0, zmaga=True, soigralec=None):
        values_iger = {
            "tri": 10,
            "dva": 20,
            "ena": 30,
            "solo tri": 40,
            "solo dva": 50,
            "solo ena": 60,
            "berac": 70,
            "solo brez": 80,
            "valat": 250
        }

        vrednost_igre = values_iger[igra1]

        
        if igra1 == "valat" or igra1 == "berac":
            if not zmaga:
                vrednost_igre *= -1
            
            score = vrednost_igre

        else:
            if not zmaga:
                vrednost_igre *= -1
                razlika1 *= -1

            score = vrednost_igre + razlika1 + dodatne_tocke

        if self.radelci > 0:
            score *= 2
            if zmaga:
                self.izbrisi_radelc()
        
        if igra1 == "solo brez" or igra1 == "berac" or igra1 == "valat" or igra1 == "klop":
            self.dodaj_radelc()

        self.dodaj_tocke(score)        
        print(self.tocke, self.trenutne_tocke(), self.radelci)
        if not soigralec == None:
            soigralec.dodaj_tocke(score)
            print(soigralec.tocke, soigralec.trenutne_tocke(), soigralec.radelci)



    
    

