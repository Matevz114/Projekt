% rebase('osnova.tpl')
<h1>Igra</h1>
<div class='container'>
% for igralec in partija.seznam_igralcev:
% if not partija.seznam_igralcev.index(igralec) == 0:
  <div class="vl"></div>
  <!--  Morda obstaja boljsi nacin za navpicno crto  -->
%end
  <div>
    <p>{{igralec.ime}}</p>
    <hr>
    <!--  Radi bi vodoravno crto cez celo, morda tezave s tem kako container svoje childe razširi oz. ne razširi (flexbox?)   -->
    <p>
    {{" O" * igralec.radelci}}
    </p>
    <hr>
    <table>
        % for i in range(len(igralec.tocke)):
        <tr>
            <td 
            % if i == len(igralec.tocke) - 1:
            class="tockezadnje"
            %else: 
            class="tocke"
            %end
            >{{igralec.tocke[i]}}</td>
        </tr>
        % end
    </table>
    <div class="gumbi">
        <form action="/razpredelnica" method="post">
            <!-- PLACEHOLDER FORM ACTION SE ZA POGRUNTAT -->
            <input type="hidden" name="igralec" value={{igralec.ime}} />
            <label for="igre">Izberi igro: </label>
            <select name="igre" id="igre">
                <option value="tri">Tri</option>
                <option value="dva">Dva</option>
                <option value="ena">Ena</option>
                <option value="solo tri">Solo tri</option>
                <option value="solo dva">Solo dva</option>
                <option value="solo ena">Solo ena</option>
                <option value="berac">Berač</option>
                <option value="solo brez">Solo brez</option>
                <option value="valat">Valat</option>
                <option value="klop">Klop</option>
            </select>            
            <br><br>
            <label for="razlika">Razlika:</label>
            <input type="number" id="razlika" name="razlika" value="0"><br><br>
            <label for="dodatne">Dodatne točke:</label>
            <input type="number" id="dodatne" name="dodatne" value="0"><br><br>
            <input type="radio" id="zmaga" name="zmaga" value="zmaga" checked>
            <label for="html">Zmaga</label> 
            <input type="radio" id="poraz" name="zmaga" value="poraz">
            <label for="css">Poraz</label> <br><br>
            <label for="soigralec">Soigralec: </label>
            <select name="soigralec" id="soigralec">
                <option value="sam">Nihče</option>
                <!-- Mogoče ti bolj prav pride, da je ta value namesto "sam" pač ime igralca samega, npr
                    Matevž izbere opcijo "Nihče," value optiona pa je "Matevž", isto kot pri drugih pride od SOIGRALEC.IME
                    To bi bilo potrebno potem v Testiranje.py ustrezno hendlat, npr for player if value==player.name, je sam -->
                % for soigralec in partija.seznam_igralcev:
                % if soigralec != igralec:
                <option value={{soigralec.ime}}>{{soigralec.ime}}</option>
                % end
                % end
            </select><br><br>
            <input type="submit" value="{{igralec.ime}} igra!">
        </form>
        <form action="/razpredelnica" method="post">
            <input type="hidden" name="igralec" value={{igralec.ime}} />
            <input type="hidden" name="igre" value="rocno" />
            <label for="dodatne">Dodaj/odvzemi točke: </label>
            <input type="number" name="dodatne" value="0" />
            <input type="submit" value="Piši!">
        </form>
        
    </div>
  </div>
  
% end
</div>